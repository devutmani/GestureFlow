# GestureFlow / models /

This folder holds the optional **Vosk offline speech recognition model**.

Without a model here, GestureFlow uses **Google Speech API** (requires internet).
With a model here, voice recognition works **100% offline**, faster, and private.

## Download instructions

1. Go to: https://alphacephei.com/vosk/models
2. Download **vosk-model-small-en-us-0.15** (40 MB, fast, good accuracy)
   - For better accuracy (slower): vosk-model-en-us-0.22 (1.8 GB)
3. Extract the zip into THIS folder so the structure is:

```
GestureFlow/
  models/
    vosk-model-small-en-us-0.15/   ← extracted model folder
      am/
      conf/
      graph/
      ivector/
      README
```

4. Restart GestureFlow — it will auto-detect and use the model.

## Voice commands

| Say this         | Effect                                      |
|------------------|---------------------------------------------|
| "volume"         | Lock pinch → controls volume (any hand)     |
| "brightness"     | Lock pinch → controls brightness (any hand) |
| "stop"           | Release lock (return to hand-based mode)    |
| "mute"           | Instantly mute volume to 0%                 |
| "pause" / "play" | Toggle media play/pause                     |
