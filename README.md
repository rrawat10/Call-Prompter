# Call Prompter

Live call transcription and conversation quality monitoring, built by **Rakshit Rawat**. Call Prompter shows what each person says during a call and flags unprofessional language with a brief reason and suggested response.

## How it works

1. `start_call.py` calls your phone using Twilio.
2. Twilio sends call audio to the FastAPI server through a Media Streams websocket.
3. Deepgram transcribes the audio live. Completed turns are sent to Gemini for a conversation quality check.
4. The dashboard shows the transcript and highlights flagged turns. Redis can save call history when enabled.

By default, this is a one phone number self test. To monitor both sides of a call, set `ENABLE_AGENT_CALL=true` and add `FRIEND_PHONE_NUMBER` to `.env`.

## Architecture

```text
Phone call -> Twilio Media Stream -> FastAPI /media -> Deepgram transcription
                                              |
                                              +-> Gemini reviews completed turns
                                              +-> Dashboard receives live updates
                                              +-> Redis stores events (optional)
```

FastAPI keeps a transcription session for each audio track, so customer and agent speech can appear separately. It sends partial transcripts to the dashboard and sends completed turns to Gemini for quality analysis.

## Tech stack

- **Python + FastAPI:** TwiML endpoint, audio websocket, history endpoint, and dashboard server.
- **Twilio Media Streams:** Places the test call and sends live call audio.
- **Deepgram:** Streaming speech to text for the current implementation.
- **Gemini (`google-genai`):** Reviews completed turns and returns flags with reasons and advice.
- **Redis (optional):** Stores call history and publishes transcript updates.
- **HTML, CSS, and JavaScript:** Displays the live conversation and flags in the browser.

## Setup

Install Python dependencies and copy the example configuration:

```bash
pip install -r requirements.txt
cp .env.example .env
```

On Windows PowerShell, use `Copy-Item .env.example .env` instead of `cp` if needed.

Fill in `.env` with your Twilio credentials and phone numbers, `DEEPGRAM_API_KEY`, and `GEMINI_API_KEY`. To save call history, start Redis and leave `REDIS_ENABLED=true`. Otherwise, set `REDIS_ENABLED=false`.

Twilio needs a public address for your server. For a local test, run:

```bash
ngrok http 8000
```

Put the ngrok hostname in `PUBLIC_HOST` in `.env` without `https://` (for example, `example.ngrok-free.app`).

## Run

Start the server:

```bash
uvicorn server:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000/` to see the dashboard. In another terminal, place the test call:

```bash
python start_call.py
```

Answer your phone and speak. You should see the live transcript appear in the dashboard; completed turns that Gemini flags will show a reason and guidance.

## Notes

- The quality check covers more than profanity, including disrespect, threats, and dismissive language. Its output depends on the accuracy of the transcript and the model response.
- The dashboard and call history endpoint have no login. Keep this a local test until access control is added.
- Tell participants about transcription and get any consent required before using this with another person.
- `.env` is ignored by Git so credentials stay out of the repository.

**Author:** [Rakshit Rawat](https://github.com/rrawat10)
