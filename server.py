# import asyncio,base64,json,os
# from datetime import datetime,timezone
# from pathlib import Path
# import redis.asyncio as redis
# import websockets
# from dotenv import load_dotenv
# from fastapi import FastAPI,Request,WebSocket,WebSocketDisconnect
# from fastapi.responses import HTMLResponse,PlainTextResponse
# from google import genai

# load_dotenv()
# PUBLIC_HOST=os.getenv("PUBLIC_HOST")
# MY_PHONE_NUMBER=os.getenv("MY_PHONE_NUMBER")
# FRIEND_PHONE_NUMBER=os.getenv("FRIEND_PHONE_NUMBER")
# ENABLE_AGENT_CALL=os.getenv("ENABLE_AGENT_CALL","false").lower()=="true"
# DEEPGRAM_API_KEY=os.getenv("DEEPGRAM_API_KEY")
# DEEPGRAM_MODEL=os.getenv("DEEPGRAM_MODEL","nova-3")
# DEEPGRAM_LANGUAGE=os.getenv("DEEPGRAM_LANGUAGE","multi")
# GEMINI_API_KEY=os.getenv("GEMINI_API_KEY")
# GEMINI_MODEL=os.getenv("GEMINI_MODEL","gemini-3.6-flash")
# REDIS_ENABLED=os.getenv("REDIS_ENABLED","true").lower()=="true"
# REDIS_URL=os.getenv("REDIS_URL","redis://localhost:6379/0")
# SYSTEM_PROMPT_PATH=Path(__file__).with_name("system_prompts.txt")
# SYSTEM_PROMPT=SYSTEM_PROMPT_PATH.read_text(encoding="utf-8") if SYSTEM_PROMPT_PATH.exists() else "Analyze the conversation for genuine rude, impolite, abusive, threatening, or unprofessional language. Do not flag normal conversation. Return JSON only."
# app=FastAPI()
# gemini=genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
# redis_client=redis.from_url(REDIS_URL,decode_responses=True) if REDIS_ENABLED else None
# dashboard_clients=set()
# TRACK_SPEAKERS={"inbound":"Customer","inbound_track":"Customer","outbound":"Agent","outbound_track":"Agent"}

# def timestamp(): return datetime.now(timezone.utc).isoformat()
# def clean_text(text): return " ".join((text or "").strip().split())

# async def broadcast(data):
#     dead=[]
#     for ws in list(dashboard_clients):
#         try: await ws.send_json(data)
#         except Exception: dead.append(ws)
#     for ws in dead: dashboard_clients.discard(ws)

# async def save_redis(call_sid,data):
#     if not redis_client or not call_sid: return
#     try:
#         payload=json.dumps(data,ensure_ascii=False)
#         await redis_client.rpush(f"transcript:{call_sid}",payload)
#         if data.get("type")=="transcript_update" and data.get("turn_status")=="completed":
#             turn={"turn":data.get("turn_number"),"speaker":data.get("speaker","Unknown"),"role":data.get("speaker","Unknown").lower(),"text":data.get("text",""),"timestamp":data.get("timestamp")}
#             await redis_client.rpush(f"chat_history:{call_sid}",json.dumps(turn,ensure_ascii=False))
#             await redis_client.publish("chat_history_updates",json.dumps({"session_id":call_sid,**turn},ensure_ascii=False))
#         await redis_client.publish("transcript_updates",payload)
#     except Exception as e: print(f"[Redis] {e}",flush=True)

# async def publish(call_sid,data):
#     await broadcast(data)
#     if redis_client and call_sid: asyncio.create_task(save_redis(call_sid,data))

# async def analyze_speech(text,speaker):
#     text=clean_text(text)
#     neutral={"flagged":False,"severity":"none","category":"none","reason":"","evidence":"","advice":""}
#     if not text or not gemini: return neutral
#     prompt=f"""{SYSTEM_PROMPT}

# Speaker: {speaker}
# Analyze ONLY this one completed conversational turn.

# TRANSCRIPT:
# {text}

# Rules:
# - Normal conversation MUST be neutral.
# - Do not flag greetings, please/thank-you, normal questions/requests/complaints, normal frustration, repetition, short or incomplete STT wording, casual Hindi/Hinglish, "यार", "भाई", "sir", "जल्दी बताओ" by themselves, or asking whether somebody can hear/understand.
# - Flag only genuine insults, profanity, personal attacks, contempt, hostile/aggressive language, threats, harassment, discrimination, mocking/humiliation, or clearly unprofessional Agent behavior.
# - Do not infer negative intent from incomplete transcript.
# - Evidence MUST be an exact phrase from the transcript. Never invent evidence.
# - LOW=mild genuine impoliteness; MEDIUM=clear insult/disrespect/aggression; HIGH=severe abuse, threat, strong profanity, harassment, discrimination, or serious intimidation.
# - Do not classify normal impatience as HIGH.
# - Advice must correspond to the issue.

# Return ONLY JSON:
# {{"flagged":true,"severity":"low|medium|high|none","category":"profanity|insult|disrespect|aggressive|impatience|mocking|dismissive|discrimination|sexual|threat|none","reason":"short specific reason","evidence":"exact problematic phrase or empty string","advice":"appropriate advice or empty string"}}

# For normal speech:
# {{"flagged":false,"severity":"none","category":"none","reason":"","evidence":"","advice":""}}
# """
#     try:
#         r=await asyncio.to_thread(gemini.models.generate_content,model=GEMINI_MODEL,contents=prompt,config={"response_mime_type":"application/json"})
#         raw=(r.text or "").strip()
#         if raw.startswith("```"): raw=raw.replace("```json","").replace("```","").strip()
#         result=json.loads(raw)
#         if not result.get("flagged"): return neutral
#         return {"flagged":True,"severity":result.get("severity","low"),"category":result.get("category","disrespect"),"reason":result.get("reason","Inappropriate language detected."),"evidence":result.get("evidence",text),"advice":result.get("advice","Please remain polite, calm, respectful, and professional.")}
#     except Exception as e:
#         print(f"[Gemini analysis ERROR] {e}",flush=True)
#         return neutral

# class STTSession:
#     def __init__(self,call_sid,track,speaker):
#         self.call_sid=call_sid;self.track=track;self.speaker=speaker;self.ws=None;self.reader=None;self.stopping=False;self.turn=0;self.final_parts=[]
#     async def start(self):
#         if not DEEPGRAM_API_KEY: raise RuntimeError("DEEPGRAM_API_KEY is missing.")
#         url=f"wss://api.deepgram.com/v1/listen?model={DEEPGRAM_MODEL}&language={DEEPGRAM_LANGUAGE}&encoding=mulaw&sample_rate=8000&channels=1&interim_results=true&smart_format=true&punctuate=true&endpointing=500&utterance_end_ms=1000&vad_events=true"
#         self.ws=await websockets.connect(url,additional_headers={"Authorization":f"Token {DEEPGRAM_API_KEY}"},ping_interval=10,ping_timeout=10,max_size=None)
#         self.reader=asyncio.create_task(self.read())
#         print(f"[Deepgram] connected | {self.speaker} | {self.track}",flush=True)
#     async def read(self):
#         try:
#             async for raw in self.ws:
#                 d=json.loads(raw)
#                 if d.get("type")!="Results": continue
#                 a=d.get("channel",{}).get("alternatives",[])
#                 if not a: continue
#                 text=clean_text(a[0].get("transcript",""))
#                 if text: await self.handle(text,bool(d.get("is_final")),bool(d.get("speech_final")))
#         except asyncio.CancelledError: raise
#         except Exception as e:
#             if not self.stopping: print(f"[Deepgram reader] {self.speaker}: {e}",flush=True)
#     async def handle(self,text,is_final,speech_final):
#         if is_final: self.final_parts.append(text)
#         if not speech_final:
#             await publish(self.call_sid,{"type":"transcript_update","call_sid":self.call_sid,"track":self.track,"speaker":self.speaker,"provider":"deepgram","text":text,"is_final":is_final,"speech_final":False,"turn_number":self.turn,"turn_status":"live","timestamp":timestamp()})
#             print(f"[deepgram][{'FINAL' if is_final else 'LIVE'}] {self.speaker}: {text}",flush=True)
#             return
#         completed=clean_text(" ".join(self.final_parts));self.final_parts=[]
#         if not completed:return
#         self.turn+=1
#         print(f"[TURN {self.turn}] {self.speaker}: {completed}",flush=True)
#         await publish(self.call_sid,{"type":"transcript_update","call_sid":self.call_sid,"track":self.track,"speaker":self.speaker,"provider":"deepgram","text":completed,"is_final":True,"speech_final":True,"turn_number":self.turn,"turn_status":"completed","timestamp":timestamp()})
#         asyncio.create_task(self.flag(completed,self.turn))
#     async def flag(self,text,turn_number):
#         r=await analyze_speech(text,self.speaker);flagged=bool(r.get("flagged"));severity=r.get("severity","none");category=r.get("category","none")
#         print(f"[QUALITY] {self.speaker} | Turn {turn_number} | flagged={flagged} | severity={severity} | category={category}",flush=True)
#         if flagged:
#             print(f"[FLAGGED] {self.speaker}: {text}",flush=True);print(f"  Evidence : {r.get('evidence','')}",flush=True);print(f"  Reason   : {r.get('reason','')}",flush=True);print(f"  Advice   : {r.get('advice','')}",flush=True)
#         else: print(f"[NEUTRAL] {self.speaker}: {text}",flush=True)
#         await publish(self.call_sid,{"type":"analysis_complete","call_sid":self.call_sid,"track":self.track,"speaker":self.speaker,"turn_number":turn_number,"text":text,"flagged":flagged,"severity":severity,"category":category,"reason":r.get("reason",""),"evidence":r.get("evidence",""),"advice":r.get("advice",""),"timestamp":timestamp()})
#         if flagged: await publish(self.call_sid,{"type":"flag","call_sid":self.call_sid,"track":self.track,"speaker":self.speaker,"turn_number":turn_number,"provider":"gemini","text":text,"evidence":r.get("evidence",""),"reason":r.get("reason","Improper language detected."),"category":category,"severity":severity,"advice":r.get("advice","Please remain polite, calm, respectful, and professional."),"timestamp":timestamp()})
#     async def send(self,audio):
#         if self.ws:
#             try: await self.ws.send(audio)
#             except Exception as e:
#                 if not self.stopping: print(f"[Deepgram send] {e}",flush=True)
#     async def stop(self):
#         if self.stopping:return
#         self.stopping=True
#         if self.ws:
#             try: await self.ws.send(json.dumps({"type":"Finalize"}));await asyncio.sleep(.35)
#             except Exception:pass
#             try: await self.ws.close()
#             except Exception:pass
#         if self.reader:
#             if not self.reader.done():self.reader.cancel()
#             await asyncio.gather(self.reader,return_exceptions=True)

# @app.post("/twiml")
# async def twiml(request:Request):
#     if not PUBLIC_HOST:return PlainTextResponse("PUBLIC_HOST is missing",status_code=500)
#     url=f"wss://{PUBLIC_HOST}/media"
#     if ENABLE_AGENT_CALL and FRIEND_PHONE_NUMBER:
#         track="both_tracks";dial=f'<Dial answerOnBridge="true" timeout="30"><Number>{FRIEND_PHONE_NUMBER}</Number></Dial>'
#     else:
#         track="inbound_track";dial='<Say>This call is being transcribed for a test. Please start talking now.</Say><Pause length="120"/>'
#     return PlainTextResponse(f'<?xml version="1.0" encoding="UTF-8"?><Response><Start><Stream url="{url}" track="{track}"/></Start>{dial}</Response>',media_type="text/xml")


# @app.websocket("/media")
# async def media(ws: WebSocket):
#     await ws.accept()
#     call_sid = None
#     sessions = {}

#     try:
#         while True:
#             d = json.loads(await ws.receive_text())
#             event = d.get("event")

#             if event == "start":
#                 call_sid = d.get("start", {}).get("callSid")
#                 print(f"CALL STARTED: {call_sid}\nSTT PROVIDER: deepgram", flush=True)
#                 await publish(call_sid, {
#                     "type": "call_started",
#                     "call_sid": call_sid,
#                     "session_id": call_sid,
#                     "provider": "deepgram",
#                     "timestamp": timestamp()
#                 })

#             elif event == "media":
#                 m = d.get("media", {})
#                 track = m.get("track", "inbound")
#                 speaker = TRACK_SPEAKERS.get(track, "Customer")

#                 if track not in sessions:
#                     sessions[track] = STTSession(call_sid, track, speaker)
#                     await sessions[track].start()
#                     print(f"TRACK: {track} -> {speaker}", flush=True)

#                 if m.get("payload"):
#                     await sessions[track].send(base64.b64decode(m["payload"]))

#             elif event == "stop":
#                 print(f"CALL STOPPED: {call_sid}", flush=True)
#                 await asyncio.gather(
#                     *(s.stop() for s in sessions.values()),
#                     return_exceptions=True
#                 )
#                 await publish(call_sid, {
#                     "type": "call_stopped",
#                     "call_sid": call_sid,
#                     "timestamp": timestamp()
#                 })
#                 break

#     except WebSocketDisconnect:
#         print(f"Twilio disconnected: {call_sid}", flush=True)

#     except Exception as e:
#         print(f"[Media ERROR] {e}", flush=True)

#     finally:
#         await asyncio.gather(
#             *(s.stop() for s in sessions.values()),
#             return_exceptions=True
#         )


# @app.get("/session/{session_id}/history")
# async def session_history(session_id:str):
#     if not redis_client:return {"session_id":session_id,"turns":[]}
#     try:
#         x=await redis_client.lrange(f"chat_history:{session_id}",0,-1)
#         return {"session_id":session_id,"turns":[json.loads(i) for i in x]}
#     except Exception as e:
#         print(f"[History] {e}",flush=True);return {"session_id":session_id,"turns":[],"error":str(e)}

# @app.get("/",response_class=HTMLResponse)
# async def dashboard():
#     p=os.path.join(os.path.dirname(__file__),"dashboard.html")
#     if not os.path.exists(p):return HTMLResponse("<h2>Voicebot server is running.</h2><p>dashboard.html not found.</p>")
#     with open(p,encoding="utf-8") as f:return f.read()

# @app.websocket("/ws/dashboard")
# async def dashboard_ws(ws:WebSocket):
#     await ws.accept();dashboard_clients.add(ws);print("[Dashboard] connected",flush=True)
#     try:
#         while True:await ws.receive_text()
#     except WebSocketDisconnect:dashboard_clients.discard(ws)
#     except Exception as e:dashboard_clients.discard(ws);print(f"[Dashboard] {e}",flush=True)




















































import asyncio
import base64
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import redis.asyncio as redis
import websockets
from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, PlainTextResponse
from google import genai

load_dotenv()

PUBLIC_HOST = os.getenv("PUBLIC_HOST")
MY_PHONE_NUMBER = os.getenv("MY_PHONE_NUMBER")
FRIEND_PHONE_NUMBER = os.getenv("FRIEND_PHONE_NUMBER")
ENABLE_AGENT_CALL = os.getenv("ENABLE_AGENT_CALL", "false").lower() == "true"

DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
DEEPGRAM_MODEL = os.getenv("DEEPGRAM_MODEL", "nova-3")
DEEPGRAM_LANGUAGE = os.getenv("DEEPGRAM_LANGUAGE", "multi")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

REDIS_ENABLED = os.getenv("REDIS_ENABLED", "true").lower() == "true"
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

SYSTEM_PROMPT_PATH = Path(__file__).with_name("system_prompts.txt")
if not SYSTEM_PROMPT_PATH.exists():
    raise FileNotFoundError(f"system_prompts.txt not found: {SYSTEM_PROMPT_PATH}")
SYSTEM_PROMPT = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")

app = FastAPI(
    title="Call Prompter",
    description="Real-time call transcription and conversation-quality monitoring.",
    version="1.0.0",
)

gemini = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
redis_client = redis.from_url(REDIS_URL, decode_responses=True) if REDIS_ENABLED else None
dashboard_clients = set()

TRACK_SPEAKERS = {
    "inbound": "Customer",
    "inbound_track": "Customer",
    "outbound": "Agent",
    "outbound_track": "Agent",
}

def timestamp():
    return datetime.now(timezone.utc).isoformat()

def clean_text(text):
    return " ".join((text or "").strip().split())

async def broadcast(data):
    dead = []
    for ws in list(dashboard_clients):
        try:
            await ws.send_json(data)
        except Exception:
            dead.append(ws)
    for ws in dead:
        dashboard_clients.discard(ws)

async def save_redis(call_sid, data):
    if not redis_client or not call_sid:
        return
    try:
        payload = json.dumps(data, ensure_ascii=False)
        await redis_client.rpush(f"transcript:{call_sid}", payload)

        if data.get("type") == "transcript_update" and data.get("turn_status") == "completed":
            turn = {
                "turn": data.get("turn_number"),
                "speaker": data.get("speaker", "Unknown"),
                "role": data.get("speaker", "Unknown").lower(),
                "text": data.get("text", ""),
                "timestamp": data.get("timestamp")
            }
            await redis_client.rpush(
                f"chat_history:{call_sid}",
                json.dumps(turn, ensure_ascii=False)
            )
            await redis_client.publish(
                "chat_history_updates",
                json.dumps({"session_id": call_sid, **turn}, ensure_ascii=False)
            )

        await redis_client.publish("transcript_updates", payload)
    except Exception as e:
        print(f"[Redis] {e}", flush=True)

async def publish(call_sid, data):
    await broadcast(data)
    if redis_client and call_sid:
        asyncio.create_task(save_redis(call_sid, data))

async def analyze_speech(text, speaker):
    text = clean_text(text)
    neutral = {
        "flagged": False,
        "severity": "none",
        "category": "none",
        "reason": "",
        "evidence": "",
        "advice": ""
    }

    if not text or not gemini:
        return neutral

    prompt = f"""{SYSTEM_PROMPT}

Speaker: {speaker}

TRANSCRIPT:
{text}
"""

    try:
        response = await asyncio.to_thread(
            gemini.models.generate_content,
            model=GEMINI_MODEL,
            contents=prompt,
            config={"response_mime_type": "application/json"}
        )

        raw = (response.text or "").strip()

        if raw.startswith("```"):
            raw = raw.replace("```json", "").replace("```", "").strip()

        result = json.loads(raw)

        if not result.get("flagged"):
            return neutral

        return {
            "flagged": True,
            "severity": result.get("severity", "low"),
            "category": result.get("category", "disrespect"),
            "reason": result.get("reason", "Inappropriate language detected."),
            "evidence": result.get("evidence", ""),
            "advice": result.get(
                "advice",
                "Please remain polite, calm, respectful, and professional."
            )
        }

    except Exception as e:
        print(f"[Gemini analysis ERROR] {e}", flush=True)
        return neutral

class STTSession:
    def __init__(self, call_sid, track, speaker):
        self.call_sid = call_sid
        self.track = track
        self.speaker = speaker
        self.ws = None
        self.reader = None
        self.stopping = False
        self.turn = 0
        self.final_parts = []

    async def start(self):
        if not DEEPGRAM_API_KEY:
            raise RuntimeError("DEEPGRAM_API_KEY is missing.")

        url = (
            "wss://api.deepgram.com/v1/listen"
            f"?model={DEEPGRAM_MODEL}"
            f"&language={DEEPGRAM_LANGUAGE}"
            "&encoding=mulaw"
            "&sample_rate=8000"
            "&channels=1"
            "&interim_results=true"
            "&smart_format=true"
            "&punctuate=true"
            "&endpointing=500"
            "&utterance_end_ms=1000"
            "&vad_events=true"
        )

        self.ws = await websockets.connect(
            url,
            additional_headers={"Authorization": f"Token {DEEPGRAM_API_KEY}"},
            ping_interval=10,
            ping_timeout=10,
            max_size=None
        )

        self.reader = asyncio.create_task(self.read())
        print(
            f"[Deepgram] connected | {self.speaker} | {self.track}",
            flush=True
        )

    async def read(self):
        try:
            async for raw in self.ws:
                data = json.loads(raw)

                if data.get("type") != "Results":
                    continue

                alternatives = (
                    data.get("channel", {})
                    .get("alternatives", [])
                )

                if not alternatives:
                    continue

                text = clean_text(
                    alternatives[0].get("transcript", "")
                )

                if text:
                    await self.handle(
                        text,
                        bool(data.get("is_final")),
                        bool(data.get("speech_final"))
                    )

        except asyncio.CancelledError:
            raise
        except Exception as e:
            if not self.stopping:
                print(
                    f"[Deepgram reader] {self.speaker}: {e}",
                    flush=True
                )

    async def handle(self, text, is_final, speech_final):
        if is_final:
            self.final_parts.append(text)

        if not speech_final:
            await publish(
                self.call_sid,
                {
                    "type": "transcript_update",
                    "call_sid": self.call_sid,
                    "track": self.track,
                    "speaker": self.speaker,
                    "provider": "deepgram",
                    "text": text,
                    "is_final": is_final,
                    "speech_final": False,
                    "turn_number": self.turn,
                    "turn_status": "live",
                    "timestamp": timestamp()
                }
            )

            print(
                f"[deepgram][{'FINAL' if is_final else 'LIVE'}] "
                f"{self.speaker}: {text}",
                flush=True
            )
            return

        completed = clean_text(" ".join(self.final_parts))
        self.final_parts = []

        if not completed:
            return

        self.turn += 1

        print(
            f"[TURN {self.turn}] {self.speaker}: {completed}",
            flush=True
        )

        await publish(
            self.call_sid,
            {
                "type": "transcript_update",
                "call_sid": self.call_sid,
                "track": self.track,
                "speaker": self.speaker,
                "provider": "deepgram",
                "text": completed,
                "is_final": True,
                "speech_final": True,
                "turn_number": self.turn,
                "turn_status": "completed",
                "timestamp": timestamp()
            }
        )

        asyncio.create_task(
            self.flag(completed, self.turn)
        )

    async def flag(self, text, turn_number):
        result = await analyze_speech(text, self.speaker)

        flagged = bool(result.get("flagged"))
        severity = result.get("severity", "none")
        category = result.get("category", "none")

        print(
            f"[QUALITY] {self.speaker} | Turn {turn_number} | "
            f"flagged={flagged} | severity={severity} | category={category}",
            flush=True
        )

        if flagged:
            print(f"[FLAGGED] {self.speaker}: {text}", flush=True)
            print(
                f"  Evidence : {result.get('evidence', '')}",
                flush=True
            )
            print(
                f"  Reason   : {result.get('reason', '')}",
                flush=True
            )
            print(
                f"  Advice   : {result.get('advice', '')}",
                flush=True
            )
        else:
            print(
                f"[NEUTRAL] {self.speaker}: {text}",
                flush=True
            )

        await publish(
            self.call_sid,
            {
                "type": "analysis_complete",
                "call_sid": self.call_sid,
                "track": self.track,
                "speaker": self.speaker,
                "turn_number": turn_number,
                "text": text,
                "flagged": flagged,
                "severity": severity,
                "category": category,
                "reason": result.get("reason", ""),
                "evidence": result.get("evidence", ""),
                "advice": result.get("advice", ""),
                "timestamp": timestamp()
            }
        )

        if flagged:
            await publish(
                self.call_sid,
                {
                    "type": "flag",
                    "call_sid": self.call_sid,
                    "track": self.track,
                    "speaker": self.speaker,
                    "turn_number": turn_number,
                    "provider": "gemini",
                    "text": text,
                    "evidence": result.get("evidence", ""),
                    "reason": result.get(
                        "reason",
                        "Improper language detected."
                    ),
                    "category": category,
                    "severity": severity,
                    "advice": result.get("advice", ""),
                    "timestamp": timestamp()
                }
            )

    async def send(self, audio):
        if self.ws:
            try:
                await self.ws.send(audio)
            except Exception as e:
                if not self.stopping:
                    print(f"[Deepgram send] {e}", flush=True)

    async def stop(self):
        if self.stopping:
            return

        self.stopping = True

        if self.ws:
            try:
                await self.ws.send(
                    json.dumps({"type": "Finalize"})
                )
                await asyncio.sleep(0.35)
            except Exception:
                pass

            try:
                await self.ws.close()
            except Exception:
                pass

        if self.reader:
            if not self.reader.done():
                self.reader.cancel()

            await asyncio.gather(
                self.reader,
                return_exceptions=True
            )

@app.post("/twiml")
async def twiml(request: Request):
    if not PUBLIC_HOST:
        return PlainTextResponse(
            "PUBLIC_HOST is missing",
            status_code=500
        )

    url = f"wss://{PUBLIC_HOST}/media"

    if ENABLE_AGENT_CALL and FRIEND_PHONE_NUMBER:
        track = "both_tracks"
        dial = (
            '<Dial answerOnBridge="true" timeout="30">'
            f"<Number>{FRIEND_PHONE_NUMBER}</Number>"
            "</Dial>"
        )
    else:
        track = "inbound_track"
        dial = (
            "<Say>"
            "This call is being transcribed for a test. "
            "Please start talking now."
            "</Say>"
            '<Pause length="120"/>'
        )

    return PlainTextResponse(
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f'<Start><Stream url="{url}" track="{track}"/></Start>'
        f"{dial}"
        "</Response>",
        media_type="text/xml"
    )

@app.websocket("/media")
async def media(ws: WebSocket):
    await ws.accept()

    call_sid = None
    sessions = {}

    try:
        while True:
            data = json.loads(
                await ws.receive_text()
            )

            event = data.get("event")

            if event == "start":
                call_sid = (
                    data
                    .get("start", {})
                    .get("callSid")
                )

                print(
                    f"CALL STARTED: {call_sid}\n"
                    f"STT PROVIDER: deepgram",
                    flush=True
                )

                await publish(
                    call_sid,
                    {
                        "type": "call_started",
                        "call_sid": call_sid,
                        "session_id": call_sid,
                        "provider": "deepgram",
                        "timestamp": timestamp()
                    }
                )

            elif event == "media":
                media_data = data.get("media", {})
                track = media_data.get(
                    "track",
                    "inbound"
                )

                speaker = TRACK_SPEAKERS.get(
                    track,
                    "Customer"
                )

                if track not in sessions:
                    sessions[track] = STTSession(
                        call_sid,
                        track,
                        speaker
                    )

                    await sessions[track].start()

                    print(
                        f"TRACK: {track} -> {speaker}",
                        flush=True
                    )

                payload = media_data.get("payload")

                if payload:
                    await sessions[track].send(
                        base64.b64decode(payload)
                    )

            elif event == "stop":
                print(
                    f"CALL STOPPED: {call_sid}",
                    flush=True
                )

                await asyncio.gather(
                    *(
                        session.stop()
                        for session in sessions.values()
                    ),
                    return_exceptions=True
                )

                await publish(
                    call_sid,
                    {
                        "type": "call_stopped",
                        "call_sid": call_sid,
                        "timestamp": timestamp()
                    }
                )

                break

    except WebSocketDisconnect:
        print(
            f"Twilio disconnected: {call_sid}",
            flush=True
        )

    except Exception as e:
        print(
            f"[Media ERROR] {e}",
            flush=True
        )

    finally:
        await asyncio.gather(
            *(
                session.stop()
                for session in sessions.values()
            ),
            return_exceptions=True
        )

@app.get("/session/{session_id}/history")
async def session_history(session_id: str):
    if not redis_client:
        return {
            "session_id": session_id,
            "turns": []
        }

    try:
        items = await redis_client.lrange(
            f"chat_history:{session_id}",
            0,
            -1
        )

        return {
            "session_id": session_id,
            "turns": [
                json.loads(item)
                for item in items
            ]
        }

    except Exception as e:
        print(
            f"[History] {e}",
            flush=True
        )

        return {
            "session_id": session_id,
            "turns": [],
            "error": str(e)
        }

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    path = os.path.join(
        os.path.dirname(__file__),
        "dashboard.html"
    )

    if not os.path.exists(path):
        return HTMLResponse(
            "<h2>Voicebot server is running.</h2>"
            "<p>dashboard.html not found.</p>"
        )

    with open(path, encoding="utf-8") as file:
        return file.read()

@app.websocket("/ws/dashboard")
async def dashboard_ws(ws: WebSocket):
    await ws.accept()
    dashboard_clients.add(ws)

    print(
        "[Dashboard] connected",
        flush=True
    )

    try:
        while True:
            await ws.receive_text()

    except WebSocketDisconnect:
        dashboard_clients.discard(ws)

    except Exception as e:
        dashboard_clients.discard(ws)
        print(
            f"[Dashboard] {e}",
            flush=True
        )
