# Video Summarizer

Video Summarizer is a Django web application that allows users to enter YouTube video URLs, transcribe the audio using AssemblyAI, and generate useful notes from the transcription using Google's Gemini API. Users can sign up, log in, save their notes, and view them later.

## Features

- Paste a YouTube link and get notes: a readable summary, key takeaways, timestamped chapters that jump to that moment in the video, and a short quiz
- Ask questions about a video and get answers grounded in its transcript
- Videos process in the background with live progress, so long videos don't time out and you can leave the page
- My notes: search across notes and transcripts, rename, delete, retry failed videos, and export any note as Markdown
- Uses YouTube captions when available (fast and free) and falls back to AssemblyAI transcription for videos without them
- Sign up and log in, dark mode

## Use Cases

- Students can use this app to summarize educational videos and create study notes.
- Professionals can use it to quickly grasp the key points from long video conferences or webinars.
- Researchers can use it to extract important information from video lectures or presentations.
- Content creators can use it to create outlines or summaries for their video scripts.
- Journalists can use it to quickly summarize news videos or interviews.

## Technologies Used

- Django (Python web framework)
- AssemblyAI (Speech-to-Text API)
- Gemini (Text Summarization API)
- HTML, CSS, JavaScript (Front-end)
- SQLite locally, or PostgreSQL via `DATABASE_URL`

## Installation

```
git clone https://github.com/eshanpandey/Video_Summarizer.git
cd Video_Summarizer/backend/ai_transcriber_app
python -m venv env
source env/bin/activate  # On Windows, use `env\Scripts\activate`
pip install -r requirements.txt
cp .env.example .env     # then add your GEMINI_API_KEY (and optionally ASSEMBLYAI_API_KEY)
python manage.py migrate
python manage.py runserver
```

Open `http://localhost:8000`. With no `DATABASE_URL` set the app uses a local SQLite file; set `DATABASE_URL` to use Postgres.

Transcripts come from the video's YouTube captions when available. Videos without captions are downloaded with yt-dlp and transcribed with AssemblyAI, which needs `ASSEMBLYAI_API_KEY`.

Run the tests with `python manage.py test`.

### Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `GEMINI_API_KEY` | (required) | Notes and Q&A |
| `ASSEMBLYAI_API_KEY` | empty | Transcribing videos that have no captions |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Gemini model to use |
| `DATABASE_URL` | local SQLite | e.g. `postgres://user:pass@host:5432/db` |
| `DJANGO_SECRET_KEY` | dev-only key | Required when `DJANGO_DEBUG=false` |
| `DJANGO_DEBUG` | `true` | Set `false` in production |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Comma-separated hostnames |
| `JOB_WORKERS` | `2` | Videos processed at the same time |

## Deployment

**Docker:** `docker compose up --build` from `backend/ai_transcriber_app` runs the app with Postgres on http://localhost:8000 (put your API keys in `.env` first).

**Render (one click):** the repo includes a `render.yaml` Blueprint. On render.com choose New > Blueprint, pick this repository, and enter `GEMINI_API_KEY` when prompted. It creates the web service and a Postgres database.

Summaries run in a thread pool inside the web process, so the Docker image runs a single Gunicorn worker with several threads. A job interrupted by a restart is marked failed and can be retried from its page.

## Usage

1. Sign up for a new account or log in with your existing credentials.
2. Enter the URL of a YouTube video.
3. Wait for the video to be processed. The audio will be transcribed using AssemblyAI, and the transcription will be summarized into useful notes using Gemini.
4. View the generated notes and optionally save them for future reference.
5. Access your saved notes by clicking the "Saved Notes" link in the navigation menu.


## Screenshots

![alt text](image-3.png)
![alt text](image.png)
![alt text](image-1.png)
![alt text](image-2.png)
![alt text](image-4.png)

## Contributing

Contributions are welcome! If you find any issues or have suggestions for improvements, please open an issue or submit a pull request.

## License

This project is licensed under the [MIT License](LICENSE).

## Acknowledgments

- [AssemblyAI](https://www.assemblyai.com/) for their Speech-to-Text API
- [Gemini](https://ai.google.dev/) for their Text Summarization API
- [Django](https://www.djangoproject.com/) for the web framework
