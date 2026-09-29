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

logger = logging.getLogger(__name__)

NOTES_PROMPT = """You are a notes maker. You will be given the transcript of a video.
Summarize the crux of the entire video as a blog article rather than as a video recap,
and list the important topics with a short explanation of each as points.
Write simple paragraphs and points in language that is easy for everyone to understand.
Generate plain text only, with no HTML tags or other formatting.

Transcript:
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


def get_caption_transcript(video_id):
    """Return YouTube's caption text for the video, or None if it has none."""
    from youtube_transcript_api import YouTubeTranscriptApi

    try:
        transcripts = YouTubeTranscriptApi().list(video_id)
        try:
            transcript = transcripts.find_transcript(["en"])
        except Exception:
            transcript = next(iter(transcripts))
        return " ".join(snippet.text for snippet in transcript.fetch()).strip() or None
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
    return transcript.text


def get_transcript(url):
    video_id = extract_video_id(url)
    return get_caption_transcript(video_id) or get_audio_transcript(url)


def generate_notes(transcript):
    from google import genai

    api_key = settings.GEMINI_API_KEY
    if not api_key:
        raise PipelineError("GEMINI_API_KEY is not set.")

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=NOTES_PROMPT + transcript,
        )
    except Exception as exc:
        logger.exception("Gemini request failed")
        raise PipelineError("Failed to generate notes.") from exc

    if not response.text:
        raise PipelineError("Failed to generate notes.")
    return response.text.strip()
