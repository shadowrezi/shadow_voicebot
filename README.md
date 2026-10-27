# Jarvis — PC Voice Control

Local voice assistant for Windows: listens to the microphone, recognizes speech **on this machine**, thinks with a **local neural network** (Ollama), and can actually control the system. No API keys, subscriptions, or limits.

```text
🎤 Jarvis, open the browser and take a screenshot
🔊 Opened Chrome, screenshot saved to Pictures\Jarvis.
```

## What's inside

| Layer | Technology | Notes |
|---|---|---|
| Speech recognition | faster-whisper small (CUDA) | offline, 0.1-0.8 s per phrase |
| Thinking | Ollama + Qwen 3 8B | local, no cloud |
| Voice output | Edge TTS + SAPI fallback | Russian / English |
| System control | pynput, PowerShell, WinAPI | - |

If Edge TTS is unavailable, the assistant automatically falls back to the built-in voice.

## Quick start

```bat
jarvis.bat
```

**Important:** press **PgUp** to activate, then say a command. To stop — Jarvis stops listening.

The project uses `.venv`; dependencies are installed automatically on first run. The Whisper model is about 500 MB.

Check your environment:

```bat
jarvis.bat --check
```

Calibrate the microphone:

```bat
jarvis.bat --calibrate
```

## Example commands

Say "Jarvis" or the wake word:

- "Jarvis, what time is it"
- "Jarvis, weather in Moscow" / "Jarvis, weather in London"
- "Jarvis, open Chrome"
- "Jarvis, shut down"
- "Jarvis, volume up" / "volume down" / "mute"
- "Jarvis, take a screenshot"
- "Jarvis, type hello world"
- "Jarvis, find files named report"
- "Jarvis, remind me at 17:00 to call mom"
- "Jarvis, play music" — Spotify/YouTube search

Complex tasks (search, code, files, weather, reminders) are handled by **Ollama with tools**.

## CLI

```bat
jarvis.bat                     :: start
jarvis.bat --check             :: environment check
jarvis.bat --calibrate         :: microphone calibration
jarvis.bat --list-devices      :: list input devices
jarvis.bat --device 1          :: select device by index
jarvis.bat --text "hello"      :: process one phrase without microphone
jarvis.bat --no-wake           :: disable wake word
jarvis.bat --no-tts            :: disable voice output
jarvis.bat --asr-model medium  :: choose Whisper model
jarvis.bat --model qwen3:4b    :: choose Ollama model
jarvis.bat --autostart         :: add to Windows startup
jarvis.bat --no-autostart      :: remove from startup
jarvis.bat --vocab             :: show learned words
jarvis.bat --remember word     :: remember a word
jarvis.bat --forget word       :: forget a word
```

## Vocabulary learning

Jarvis learns words automatically and stores them in `logs/vocab.json`. Hotwords are passed to Whisper, which improves recognition of names and apps.

**How it works:**
1. Whisper recognizes a word (possibly incorrectly)
2. If the command succeeds, the word is learned
3. After 2+ occurrences it becomes a hotword
4. Whisper then recognizes it better

Examples:
- "Remember word Spotify" / "Forget word Spotify"
- "What words" / "Show vocabulary"

Config in `config.json` under `asr`:
- `learn_words` - enable learning (default true)
- `hotwords` - initial hotword list
- `hotwords_limit` - max hotwords (default 40)
- `hotwords_min_count` - min occurrences to learn (default 2)

## Configuration

Edit `config.json` (created on first run):

| Key | Description |
|---|---|
| `wake_words` | wake words |
| `audio.device` | microphone: name or index |
| `audio.silence_ms` | silence length to end a phrase |
| `audio.min_rms` | minimum volume threshold |
| `asr.model` | `tiny` / `base` / `small` / `medium` |
| `asr.learn_words` | enable word learning (true/false) |
| `asr.hotwords` | words always passed to Whisper |
| `tts.voice` | Edge voice, e.g. `ru-RU-SvetlanaNeural` |
| `tts.rate` | speech rate, e.g. `+8%` |
| `llm.model` | Ollama model |
| `llm.think` | Qwen3 "thinking": slower but +2-4% quality |
| `safety.confirm_destructive` | confirm destructive actions |

Install another model:

```bat
ollama pull llama3.1:8b
```

Then set it in `config.json` under `llm.model`.

## Safety

Jarvis is cautious with destructive operations:

1. **Destructive commands are blocked** - `format`, `diskpart`, `bcdedit`, deleting `C:\Windows`, etc. are never executed, even with confirmation.
2. **PowerShell scripts are restricted** - only safe cmdlets.
3. **Deletion requires confirmation** ("yes"/"no"), and deletes go to the Recycle Bin, not permanent deletion.
4. **Audit log** - `logs/audit.jsonl`: every action, parameters, and results.
5. **Emergency stop** - `Ctrl+Alt+Q`.

Important: do not run Jarvis as Administrator unless you really need it.

## Troubleshooting

| Problem | Solution |
|---|---|
| "Ollama unavailable" | start Ollama, check `ollama list` |
| "Model not found" | `ollama pull qwen3:8b` |
| No microphone | `jarvis.bat --list-devices`, then `--device <index>` |
| Poor recognition | `--calibrate` and tune `audio.min_rms` |
| "cublas64_12.dll not found" | install `nvidia-cublas-cu12` in venv or run on CPU |
| No voice output | Edge TTS unavailable; SAPI fallback (Windows built-in voice) |
| Slow responses | `llm.think: false` and/or a smaller model (`qwen3:4b`) |

## Project structure

```text
jarvis/
  app.py             entry point, voice loop, confirmations, CLI
  audio.py           microphone capture + VAD
  asr.py             faster-whisper, hotword handling
  vocab.py           user vocabulary (hotwords)
  tts.py             Edge TTS -> mp3 -> sounddevice
  llm.py             Ollama + tool calling
  tools.py           PC tools + safety layer
  local_commands.py  fast local commands
  config.py          configuration and config.json
logs/
  jarvis.log         logs
  audit.jsonl        audit trail
  vocab.json         learned words (auto-created)
  tts_cache/         TTS cache
```

## License

Free to use. Contributions and improvements are welcome.