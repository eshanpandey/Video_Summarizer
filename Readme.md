# Video Summarizer

Video Summarizer is a Django web application that allows users to enter YouTube video URLs, transcribe the audio using AssemblyAI, and generate useful notes from the transcription using Google's Gemini API. Users can sign up, log in, save their notes, and view them later.

## Features

- User authentication (sign up, log in)
- Enter YouTube video URL
- Audio transcription using AssemblyAI
- Note generation from transcription using Gemini
- Save and view notes
- User-friendly interface

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
