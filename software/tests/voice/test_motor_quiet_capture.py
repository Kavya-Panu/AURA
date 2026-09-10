"""Exercise the actual capture wrapper's motor noise guard."""
import ast
from pathlib import Path
from types import SimpleNamespace
from threading import Event
import pytest
from hardware.device_types import CommandPriority


@pytest.mark.parametrize('fails', [False, True])
def test_capture_always_releases_motor_quiet_mode(fails):
    tree = ast.parse((Path(__file__).resolve().parents[2] / 'run_aura_brain.py')
                     .read_text(encoding='utf-8'))
    function = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and n.name == 'capture_voice')
    events = []
    class Hardware:
        def send_face_command(self, line, **kwargs):
            events.append(line)
            assert kwargs['priority'] == CommandPriority.HIGH
        def set_emotion(self, emotion):
            pass
    class Listener:
        def listen(self, **kwargs):
            events.append('record')
            if fails:
                raise RuntimeError('microphone interrupted')
            return SimpleNamespace(success=False, text='', error='no speech')
    env = dict(hardware=Hardware(), listener=Listener(), speech=None,
               voice_capture_active=Event(), CommandPriority=CommandPriority)
    module = ast.Module(body=[function], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), '<capture>', 'exec'), env)
    if fails:
        with pytest.raises(RuntimeError):
            env['capture_voice'](report_no_speech=False)
    else:
        assert env['capture_voice'](report_no_speech=False) is None
    assert events == ['MOTOR:TOP:QUIET:ON', 'record', 'MOTOR:TOP:QUIET:OFF']
    assert not env['voice_capture_active'].is_set()
