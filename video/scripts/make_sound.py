"""Compose an original local synth bed and UI sounds; no speech or model audio."""
import array
import math
import json
from pathlib import Path
import random
import wave

RATE = 44100
production = json.loads((Path(__file__).resolve().parents[1] / 'production.json').read_text())
DURATION = production['durationSeconds']
rng = random.Random(91)
audio = array.array('f', [0.0]) * (RATE * DURATION)

def note(start, duration, frequency, gain, kind='pluck'):
    base = round(start * RATE)
    for i in range(min(round(duration * RATE), len(audio) - base)):
        t = i / RATE
        attack = min(1, t / .018)
        release = min(1, (duration-t) / .14)
        env = attack * release * (math.exp(-t*3) if kind == 'pluck' else .72)
        value = math.sin(2*math.pi*frequency*t)
        value += .18 * math.sin(2*math.pi*frequency*2*t)
        audio[base+i] += value * env * gain

# Slow, open voicings: an original 90 bpm ambient/electronic composition.
chords = [(130.8128,164.8138,195.9977,293.6648),
          (110,130.8128,164.8138,246.9417),
          (87.3071,130.8128,174.6141,220),
          (97.9989,146.8324,195.9977,246.9417)]
beat = 2/3
for bar in range(math.ceil(DURATION / (beat*4))):
    start = bar*beat*4
    if start >= DURATION-2:
        break
    chord = chords[bar % 4]
    for freq in chord:
        note(start, min(3.0, DURATION-start), freq, .012, 'pad')
    for step in range(8):
        when = start+step*beat/2
        if when < DURATION-2:
            note(when, .8, chord[(step+bar) % 4]*2, .027)
    note(start, 1.3, chord[0]/2, .037)

def whoosh(start, duration=.32):
    base=round(start*RATE)
    last=0.0
    for i in range(round(duration*RATE)):
        t=i/RATE
        noise=rng.uniform(-1,1)
        last=.9*last+.1*noise
        env=math.sin(math.pi*t/duration)**2
        audio[base+i]+=last*env*.04

for moment in [scene['from']/production['fps'] for scene in production['scenes'][1:]]:
    whoosh(moment)
for moment in [frame/production['fps'] for frame in production['clickFrames']]:
    note(moment,.11,900,.045)
    note(moment+.025,.13,1350,.02)
start, pause = [frame/production['fps'] for frame in production['statusFrames']]
note(start,.42,660,.033)
note(start+.15,.48,880,.026)
note(pause,.42,440,.033)
note(pause+.15,.48,330,.026)
for moment in [34.8,35.25,35.7,36.15]:
    note(moment,.38,660,.018)

peak=max(abs(x) for x in audio)
pcm=array.array('h')
for i,value in enumerate(audio):
    t=i/RATE
    fade=min(1,t/.7,max(0,(DURATION-t)/1.7))
    # Keep the music restrained; this is not a simulated microphone comparison.
    pcm.append(round(value*fade/max(1,peak/.29)*32767))
target=Path(__file__).resolve().parents[1]/'public'/'soundtrack.wav'
target.parent.mkdir(exist_ok=True)
with wave.open(str(target),'wb') as out:
    out.setnchannels(1)
    out.setsampwidth(2)
    out.setframerate(RATE)
    out.writeframes(pcm.tobytes())
print(f'{target}: {DURATION}s, original procedural music + UI effects')
