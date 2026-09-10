"""Two-step wake acknowledgement, separate from question recording."""
import time


def acknowledge_wake(microphone, speak, *, sleep=time.sleep):
    """Discard the wake stream, finish the spoken cue, then allow capture.

    The next microphone.open() starts a fresh stream, so neither wake audio
    nor the robot's acknowledgement is passed to speech recognition.
    ``speak`` must wait for playback completion before returning.
    """
    microphone.close()
    try:
        speak("Hmm?")
    finally:
        microphone.close()
        sleep(0.20)  # allow the speaker/room tail to settle before capture
