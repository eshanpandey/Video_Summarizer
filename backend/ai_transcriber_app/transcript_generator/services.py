"""Video -> transcript -> notes pipeline.

Transcripts come from YouTube's own captions when they exist (fast and free),
and fall back to downloading the audio with yt-dlp and transcribing it with
AssemblyAI. Notes are generated with Gemini.
"""
import logging
import os
import re
import tempfile

from django.conf import settings
from pydantic import BaseModel

logger = logging.getLogger(__name__)

NOTES_PROMPT = """You are a notes maker. You will be given the transcript of a video.
Each line starts with a [mm:ss] or [h:mm:ss] timestamp.

Produce study notes for someone who has not watched the video:
- summary: the crux of the whole video written as a short blog article (not a video
  recap), in simple paragraphs separated by blank lines. Plain text, no Markdown or HTML.
- key_takeaways: 3 to 8 short, self-contained points.
- chapters: the video's main sections in order. start_seconds must come from the
  transcript timestamps. Give each a short title and a one or two sentence summary.
- quiz: 3 to 5 multiple-choice questions that check understanding of the video, each
  with 4 options, the index of the correct option, and a one-sentence explanation.

Use language that is easy for everyone to understand.

Transcript:
"""

QA_PROMPT = """Answer the question using only the video transcript below. If the transcript
doesn't cover it, say so. Be concise, use plain text, and when useful cite the [mm:ss]
timestamp where the video discusses it.

Transcript:
{transcript}

Question: {question}
"""

_VIDEO_ID_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|embed/|shorts/|live/|v/)|youtu\.be/)([A-Za-z0-9_-]{11})"
)


class PipelineError(Exception):
    """A step failed in a way the user should be told about."""

    def __init__(self, message, status=500):
        super().__init__(message)
        self.status = status


def extract_video_id(url):
    match = _VIDEO_ID_RE.search(url or "")
    if not match:
        raise PipelineError("That doesn't look like a YouTube video link.", status=400)
    return match.group(1)


def get_video_title(url):
    import yt_dlp

    try:
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True}) as ydl:
            info = ydl.extract_info(url, download=False)
        return info.get("title") or "Untitled video"
    except Exception:
        logger.exception("Could not fetch title for %s", url)
        return "Untitled video"


def format_timestamp(seconds):
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


_TRANSCRIPT_LINE_RE = re.compile(r"^\[(?:(\d+):)?(\d+):(\d{2})\]\s*(.*)$")


def parse_transcript(transcript):
    """Split '[mm:ss] text' lines back into (start_seconds, text) pairs."""
    lines = []
    for line in (transcript or "").splitlines():
        match = _TRANSCRIPT_LINE_RE.match(line.strip())
        if match:
            hours, minutes, secs, text = match.groups()
            lines.append((int(hours or 0) * 3600 + int(minutes) * 60 + int(secs), text))
        elif line.strip() and lines:
            lines[-1] = (lines[-1][0], f"{lines[-1][1]} {line.strip()}")
        elif line.strip():
            lines.append((0, line.strip()))
    return lines


def format_segments(segments, block_seconds=30):
    """Merge (start_seconds, text) segments into '[mm:ss] text' lines of ~block_seconds each."""
    lines, block_start, block_text = [], None, []
    for start, text in segments:
        text = " ".join(text.split())
        if not text:
            continue
        if block_start is not None and start - block_start >= block_seconds:
            lines.append(f"[{format_timestamp(block_start)}] {' '.join(block_text)}")
            block_start, block_text = None, []
        if block_start is None:
            block_start = start
        block_text.append(text)
    if block_text:
        lines.append(f"[{format_timestamp(block_start)}] {' '.join(block_text)}")
    return "\n".join(lines)


def get_caption_transcript(video_id):
    """Return YouTube's captions as a timestamped transcript, or None if it has none."""
    from youtube_transcript_api import YouTubeTranscriptApi

    try:
        transcripts = YouTubeTranscriptApi().list(video_id)
        try:
            transcript = transcripts.find_transcript(["en"])
        except Exception:
            transcript = next(iter(transcripts))
        segments = [(snippet.start, snippet.text) for snippet in transcript.fetch()]
        return format_segments(segments) or None
    except Exception:
        logger.info("No captions available for %s", video_id, exc_info=True)
        return None


def get_audio_transcript(url):
    """Download the audio track and transcribe it with AssemblyAI."""
    import assemblyai as aai
    import yt_dlp

    api_key = settings.ASSEMBLYAI_API_KEY
    if not api_key:
        raise PipelineError("This video has no captions and ASSEMBLYAI_API_KEY is not set.")

    with tempfile.TemporaryDirectory() as tmp_dir:
        opts = {
            "format": "bestaudio/best",
            "outtmpl": os.path.join(tmp_dir, "audio.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                audio_path = ydl.prepare_filename(info)
        except Exception as exc:
            logger.exception("Audio download failed for %s", url)
            raise PipelineError("Couldn't download the video's audio.") from exc

        aai.settings.api_key = api_key
        transcript = aai.Transcriber().transcribe(audio_path)

    if transcript.status == aai.TranscriptStatus.error or not transcript.text:
        logger.error("AssemblyAI failed for %s: %s", url, transcript.error)
        raise PipelineError("Transcription failed.")
    try:
        segments = [(sentence.start / 1000, sentence.text) for sentence in transcript.get_sentences()]
    except Exception:
        logger.warning("Could not get sentence timestamps for %s", url, exc_info=True)
        segments = [(0, transcript.text)]
    return format_segments(segments)


def get_transcript(url):
    video_id = extract_video_id(url)
    return get_caption_transcript(video_id) or get_audio_transcript(url)


class Chapter(BaseModel):
    start_seconds: int
    title: str
    summary: str


class QuizQuestion(BaseModel):
    question: str
    options: list[str]
    answer_index: int
    explanation: str


class Notes(BaseModel):
    summary: str
    key_takeaways: list[str]
    chapters: list[Chapter]
    quiz: list[QuizQuestion]


def _gemini(contents, **config):
    from google import genai
    from google.genai import types

    api_key = settings.GEMINI_API_KEY
    if not api_key:
        raise PipelineError("GEMINI_API_KEY is not set.")
    client = genai.Client(api_key=api_key)
    return client.models.generate_content(
        model=settings.GEMINI_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(**config) if config else None,
    )


def generate_notes(transcript):
    """Return Notes (summary, takeaways, chapters, quiz) for a timestamped transcript."""
    try:
        response = _gemini(
            NOTES_PROMPT + transcript,
            response_mime_type="application/json",
            response_schema=Notes,
        )
        notes = response.parsed if isinstance(response.parsed, Notes) else Notes.model_validate_json(response.text)
    except PipelineError:
        raise
    except Exception as exc:
        logger.exception("Gemini notes request failed")
        raise PipelineError("Failed to generate notes.") from exc

    if not notes.summary.strip():
        raise PipelineError("Failed to generate notes.")
    notes.quiz = [
        q for q in notes.quiz if len(q.options) >= 2 and 0 <= q.answer_index < len(q.options)
    ]
    notes.chapters.sort(key=lambda chapter: chapter.start_seconds)
    return notes


def answer_question(transcript, question):
    try:
        response = _gemini(QA_PROMPT.format(transcript=transcript, question=question))
    except PipelineError:
        raise
    except Exception as exc:
        logger.exception("Gemini Q&A request failed")
        raise PipelineError("Couldn't answer that right now.") from exc
    if not response.text:
        raise PipelineError("Couldn't answer that right now.")
    return response.text.strip()
