"""Physical top-motor checks. Close AURA and keep the motor clear first."""
import re
import time
from robot_self_test import AuraSerialTest


def main():
    test = AuraSerialTest('COM14')
    test.open()
    def command(line):
        reply = test.command(line, lambda value: value.startswith('OK'), 2)
        assert reply, (line, 'no acknowledgement')
    def status():
        reply = test.command('MOTOR:TOP:STATUS', lambda value: value.startswith('MOTOR TOP '), 2)
        assert reply, 'no motor status'
        return int(re.search(r'SPEED=(\d+)', reply).group(1))
    try:
        test.command('MIC STOP', lambda value: value == 'MIC END', 2)
        command('MOTOR:TOP:QUIET:OFF')
        command('BOOK STOP')
        command('NEUTRAL')
        command('MOTOR:TOP:STOP')
        for emotion, duration, expected in [('HAPPY',4,1), ('EXCITED',5,1),
                                             ('LOVE',4,1), ('ANGRY',5.7,2)]:
            command('NEUTRAL')
            time.sleep(.2)
            command(emotion)
            end = time.monotonic()+duration
            rises = 0
            was_running = False
            maximum = 0
            while time.monotonic() < end:
                speed = status()
                maximum = max(maximum, speed)
                if speed > 0 and not was_running:
                    rises += 1
                was_running = speed > 0
                time.sleep(.08)
            assert rises == expected, (emotion, 'pulse count', rises)
            assert maximum <= 75 and status() == 0, (emotion, 'limit/stop failure')
            print(f'PASS {emotion}: pulses={rises}, peak={maximum}, stopped', flush=True)

        command('NEUTRAL'); time.sleep(.2); command('HAPPY'); time.sleep(.2)
        command('MOTOR:TOP:QUIET:ON')
        assert status() == 0
        command('MOTOR:TOP:QUIET:OFF'); time.sleep(.4)
        assert status() == 0  # no stale emotion replay
        print('PASS question-capture quiet guard and no stale replay', flush=True)
        command('NEUTRAL'); time.sleep(.2); command('EXCITED'); time.sleep(.2)
        command('SLEEP'); time.sleep(.2)
        assert status() == 0
        print('PASS sleep stops motor', flush=True)
    finally:
        # No WAKE pulse is used; changing to Neutral restores the face only.
        for line in ['MOTOR:TOP:QUIET:OFF','NEUTRAL','MOTOR:TOP:STOP']:
            try:
                command(line)
            except Exception:
                pass
        test.close()


if __name__ == '__main__':
    main()
