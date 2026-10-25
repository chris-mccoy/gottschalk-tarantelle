#!/usr/bin/env python3
"""
perform.py -- render the braille-decoded Tarantelle (brf.py) as an expressive piano MIDI file.

The notes come from the score; everything else here -- tempo, rubato, dynamics, voicing,
articulation, pedalling -- is an interpretation layered over them.
"""
import argparse, bisect, math, random, struct, sys
from fractions import Fraction as F

sys.path.insert(0, __import__('os').path.dirname(__file__))
from brf import build

PPQ = 480
TPE = PPQ // 2                    # ticks per eighth note

DYN = {'ppp': 26, 'pp': 36, 'p': 48, 'mp': 59, 'mf': 69, 'f': 80, 'ff': 92, 'fff': 104}

# ---------------------------------------------------------------- flattening

def flatten(measures, order):
    """Notes and markers on one score time line, in eighth notes from the start."""
    notes, marks, bars = [], [], []
    for k, mi in enumerate(order):
        m = measures[mi]
        base = F(6 * k)
        bars.append({'k': k, 'num': m['num'], 'start': base, 'key': m['key'], 'text': m['text']})
        for h, evs in m['lines'].items():
            byvoice = {}
            for e in evs:
                byvoice.setdefault(e['voice'], []).append(e)
            for e in evs:
                t = base + e['t'] * 8
                for mk in e.get('markers', []):
                    marks.append((t, h, mk))
                if e['kind'] != 'chord' or e.get('alt_pair'):
                    continue
                dur = e.get('dur', F(0)) * 8
                if e.get('stem'):
                    dur = max(dur, e['stem'] * 8)
                chord = list(zip(e['pitches'], [n['small'] for n in e['notes']]))
                info = {'t': t, 'dur': dur, 'hand': e['hand'], 'line': h, 'k': k, 'pos': e['t'] * 8,
                        'artic': set(e.get('artic', [])), 'slur': e.get('slur'), 'tie': e.get('tie'),
                        'grace': e['grace'], 'fermata': e.get('fermata', False),
                        'arp': ('arpeggio',) in e.get('markers', []), 'stemmed': bool(e.get('stem'))}
                if e.get('alternate'):
                    # a fingered tremolo: alternate this chord with its partner
                    vs = byvoice[e['voice']]
                    partner = vs[vs.index(e) + 1]
                    step = e['alternate'] * 8
                    a = chord
                    b = list(zip(partner['pitches'], [n['small'] for n in partner['notes']]))
                    n = int(e['dur'] * 8 / step)
                    for j in range(n):
                        add_chord(notes, b if j % 2 else a, dict(info, t=t + j * step, dur=step, slur='note'))
                    continue
                add_chord(notes, chord, info)
    merge_ties(notes)
    return notes, sorted(marks, key=lambda x: x[0]), bars

def add_chord(notes, chord, info):
    ps = sorted(p for p, _ in chord)
    cid = len(notes)
    for p, small in chord:
        role = 'single'
        if len(ps) > 1:
            if info['hand'] == 'R':
                role = 'top' if p == ps[-1] else 'inner'
            else:
                role = 'bass' if p == ps[0] else 'inner'
        notes.append(dict(info, pitch=p, small=small, role=role, chord=cid, size=len(ps)))

def merge_ties(notes):
    notes.sort(key=lambda n: (n['t'], n['pitch']))
    starts = {}
    for i, n in enumerate(notes):
        starts.setdefault((n['t'], n['pitch']), []).append(i)
    dead = set()
    for i, n in enumerate(notes):
        if i in dead or not n['tie'] or n['grace']:
            continue
        cur = n
        while cur['tie']:
            nxt = [j for j in starts.get((cur['t'] + cur['dur'], cur['pitch']), []) if j not in dead and j != i]
            if not nxt:
                break
            j = nxt[0]
            dead.add(j)
            n['dur'] += notes[j]['dur']
            n['fermata'] = n['fermata'] or notes[j]['fermata']
            cur = notes[j]
            n['tie'] = cur['tie'] if cur is not n else None
            if not cur['tie']:
                n['tie'] = None
    notes[:] = [n for i, n in enumerate(notes) if i not in dead]

# ---------------------------------------------------------------- the interpretation

class Plan:
    """Tempo and dynamics as functions of score time (eighths)."""
    def __init__(self, notes, marks, bars, args):
        self.notes, self.marks, self.bars, self.args = notes, marks, bars, args
        self.total = len(bars) * 6
        self.words = [(t, mk[1]) for t, h, mk in marks if mk[0] == 'word']
        self.build_dynamics()
        self.build_tempo()

    # --- dynamics: a level (velocity) curve from the printed marks
    def build_dynamics(self):
        pts = []                         # (t, level or None, 'set' | 'cresc' | 'dim')
        self.accents = {}
        self.texture = []                # (t, 'tutti'|'solo'|'legg'|...)
        for t, w in self.words:
            for part in w.replace('.', ' ').split():
                if part in DYN:
                    pts.append((t, DYN[part], 'set'))
                elif part == 'fp':
                    self.accents[t] = self.accents.get(t, 0) + 14
                    pts.append((t, DYN['f'], 'set'))
                    pts.append((t + F(1, 2), DYN['p'], 'set'))
                elif part in ('sf', 'rfz', 'sfz'):
                    self.accents[t] = self.accents.get(t, 0) + 18
                elif part in ('cr', 'cresc'):
                    pts.append((t, None, 'cresc'))
                elif part == 'dim':
                    pts.append((t, None, 'dim'))
                elif part in ('tutti', 'solo', 'legg', 'dolce', 'scherz', 'brillante', 'scintillante',
                              'volante', 'martellato', 'pesante', 'impeto', 'precipitato'):
                    self.texture.append((t, part))
        # the orchestra against the soloist: an unmarked tutti enters at least forte, an
        # unmarked solo entry after it steps down a level
        marked = {int(t) // 6 for t, lv, k in pts if k == 'set'}
        for t, part in sorted(self.texture):
            if int(t) // 6 in marked:
                continue
            before = sorted((t2, lv) for t2, lv, k in pts if k == 'set' and t2 < t)
            cur = before[-1][1] if before else DYN['ff']
            if part == 'tutti' and cur < DYN['f']:
                pts.append((t, DYN['f'], 'set'))
            elif part == 'solo' and cur >= DYN['ff']:
                pts.append((t, DYN['f'], 'set'))
        pts.sort(key=lambda x: x[0])
        # resolve: a cresc/dim ramps up to the next printed level when that lies its way within
        # eight bars, else by about two steps over at most six bars; a printed level always wins
        sets = [(t, lv) for t, lv, k in pts if k == 'set']
        curve = []                       # (t, level, ramps to the next point)
        cur = DYN['ff']
        for t, lv, kind in pts:
            if kind == 'set':
                curve.append((t, lv, False)); cur = lv
                continue
            sign = 1 if kind == 'cresc' else -1
            nxt = next(((t2, l2) for t2, l2 in sets if t2 > t), None)
            end, tgt = t + 36, cur + sign * 16
            if nxt is not None:
                if nxt[0] - t <= 48 and (nxt[1] - cur) * sign > 0:
                    end, tgt = nxt[0] - F(1, 2), nxt[1]
                elif nxt[0] < end:
                    end = nxt[0] - F(1, 2)
                    tgt = cur + sign * 16 * float((end - t) / 36)
            tgt = max(DYN['pp'], min(DYN['fff'] + 4, tgt))
            curve.append((t, cur, True))
            curve.append((end, tgt, False))
            cur = tgt
        curve.sort(key=lambda x: (x[0], not x[2]))
        self.dyn_t = [c[0] for c in curve]
        self.dyn_v = [c[1] for c in curve]
        self.dyn_r = [c[2] for c in curve]
        # hairpins: swells added on top, relaxing afterwards
        self.pins = []
        open_pin = {}
        for t, h, mk in self.marks:
            if mk[0] != 'hairpin':
                continue
            if mk[1] in ('cresc', 'dim'):
                open_pin[h] = (t, mk[1])
            elif h in open_pin:
                t0, kind = open_pin.pop(h)
                if t > t0:
                    self.pins.append((t0, t, 10 if kind == 'cresc' else -10))
        tx = sorted(self.texture)
        self.tex_t = [t for t, _ in tx]
        self.tex_v = [v for _, v in tx]

    def level(self, t):
        i = bisect.bisect_right(self.dyn_t, t) - 1
        if i < 0:
            return DYN['ff']
        if self.dyn_r[i] and i + 1 < len(self.dyn_t) and self.dyn_t[i + 1] > self.dyn_t[i]:
            t0, t1 = self.dyn_t[i], self.dyn_t[i + 1]
            return self.dyn_v[i] + (self.dyn_v[i + 1] - self.dyn_v[i]) * float((t - t0) / (t1 - t0))
        return self.dyn_v[i]

    def pin(self, t):
        off = 0.0
        for t0, t1, amt in self.pins:
            if t0 <= t <= t1:
                off += amt * float((t - t0) / (t1 - t0))
            elif t1 < t <= t1 + 6:
                off += amt * (1 - float((t - t1) / 6))
        return off

    def texture_at(self, t):
        i = bisect.bisect_right(self.tex_t, t) - 1
        return self.tex_v[i] if i >= 0 else 'tutti'

    # --- tempo: seconds for each eighth of the performance
    def build_tempo(self):
        a = self.args
        base = 60.0 / a.tempo / 3            # seconds per eighth at the dotted-quarter tempo
        n = self.total
        mult = [1.0] * n                     # duration multipliers (>1 slower)
        sect = 1.0
        anim = None
        bar_word = {}
        for t, w in sorted(self.words):
            bar_word.setdefault(int(t) // 6, []).append(w)
        for b in self.bars:
            for w in [x for x in b['text']]:
                bar_word.setdefault(b['k'], []).append(w)
        # bars where a loud level or a tutti arrives: where an animando is heading
        arrive = set()
        for t, w in self.words:
            parts = w.replace('.', ' ').split()
            if any(p in ('f', 'ff', 'fff', 'tutti') for p in parts):
                arrive.add(int(t) // 6)
        # section tempo changes from the words
        sect = 1.0
        anim = None                          # (start bar, arrival bar, section factor)
        for k in range(len(self.bars)):
            for w in bar_word.get(k, []):
                if 'mosso' in w:
                    sect = a.piu_mosso; anim = None
                elif 'animando' in w:
                    k1 = next((j for j in sorted(arrive) if k < j <= k + 16), k + 8)
                    anim = (k, k1, sect)
                elif 'tempo' in w:
                    sect = 1.0; anim = None
                elif 'dolce' in w:
                    sect = 1.06
                elif 'pesante' in w:
                    sect = 1.05
                elif ('precipitato' in w or 'impeto' in w) and sect != a.piu_mosso:
                    sect = 0.97
                elif (w.startswith('tutti') or w == 'solo') and sect != a.piu_mosso:
                    sect = 1.0
            f = sect
            if anim is not None:
                k0, k1, s0 = anim
                if k <= k1:                  # press on into the arrival
                    f = s0 * (1 - 0.07 * (k - k0 + 1) / (k1 - k0 + 1))
                elif k <= k1 + 4:            # ride the climax
                    f = s0 * 0.93
                elif k <= k1 + 6:            # and settle back
                    f = s0 * (0.93 + 0.035 * (k - k1 - 4))
                else:
                    anim = None
            for j in range(6):
                mult[6 * k + j] *= f
        # the lilt of 6/8: a hair of weight on each beat
        for i in range(n):
            mult[i] *= (1.025, 0.99, 0.985)[i % 3]
        # phrase rubato over 4-bar groups: press on a little, ease at the cadence
        for i in range(n):
            x = (i % 24) / 24.0
            mult[i] *= 1 - 0.035 * math.sin(math.pi * x) + (0.06 * ((x - 0.8) / 0.2) ** 2 if x > 0.8 else 0)
        # broaden into key changes, double bars and section ends; breathe after them
        ends = set()
        for t, h, mk in self.marks:
            if mk[0] == 'bar' or mk == ('repeat_end',):
                ends.add((math.ceil(t) - 1) // 6)    # a bar line at a bar's end belongs to that bar
        for k in range(1, len(self.bars)):
            if self.bars[k]['key'] != self.bars[k - 1]['key']:
                ends.add(k - 1)
        for k in ends:
            for j in range(12):
                i = 6 * k + 5 - j
                if 0 <= i < n:
                    mult[i] *= 1 + 0.16 * ((12 - j) / 12) ** 2
            if 6 * k + 5 < n:
                mult[6 * k + 5] *= 1.25
        # fermatas
        held = set()
        for nn in self.notes:
            if nn['fermata']:
                i = int(nn['t'])
                held.update(range(i, min(n, i + max(1, int(nn['dur'])))))
        for j in held:                       # once per eighth, however many notes carry the sign
            mult[j] *= 2.0
        # the close: a broad last line
        for j in range(30):
            i = n - 1 - j
            mult[i] *= 1 + 0.30 * ((30 - j) / 30) ** 2
        self.eighth = [base * m for m in mult]
        self.start = [0.0]
        for d in self.eighth:
            self.start.append(self.start[-1] + d)

    def sec(self, t):
        """Score time (eighths, may be fractional) -> seconds."""
        t = float(t)
        i = min(int(t), len(self.eighth) - 1)
        return self.start[i] + (t - i) * self.eighth[i]

    def tick(self, s):
        """Seconds -> MIDI ticks on the tempo map that follows self.eighth."""
        i = bisect.bisect_right(self.start, s) - 1
        i = max(0, min(i, len(self.eighth) - 1))
        return int(round(TPE * (i + (s - self.start[i]) / self.eighth[i])))

# ---------------------------------------------------------------- rendering

def render(notes, marks, bars, args):
    rnd = random.Random(args.seed)
    plan = Plan(notes, marks, bars, args)
    out = []                              # (sec_on, sec_off, pitch, vel)
    by_chord = {}
    for n in notes:
        by_chord.setdefault(n['chord'], []).append(n)
    # next onset per hand, for legato
    onsets = {}
    for n in notes:
        if not n['grace']:
            onsets.setdefault(n['hand'], set()).add(n['t'])
    onset_list = {h: sorted(v) for h, v in onsets.items()}

    def next_onset(h, t):
        lst = onset_list.get(h, [])
        i = bisect.bisect_right(lst, t)
        return lst[i] if i < len(lst) else None

    # the melody's contour: a line rising above its surroundings grows, falling away recedes
    mel = sorted((c[0]['t'], max(n['pitch'] for n in c)) for c in by_chord.values()
                 if c[0]['hand'] == 'R' and not c[0]['grace'])
    mel_t = [m[0] for m in mel]
    contour = {}
    for cid, c in by_chord.items():
        t = c[0]['t']
        lo, hi = bisect.bisect_left(mel_t, t - 12), bisect.bisect_right(mel_t, t + 12)
        if hi - lo < 3:
            continue
        mean = sum(m[1] for m in mel[lo:hi]) / (hi - lo)
        top = max(n['pitch'] for n in c)
        contour[cid] = max(-6.0, min(6.0, 0.45 * (top - mean))) if c[0]['hand'] == 'R' else 0.0

    graces = {}
    for n in notes:
        if n['grace']:
            graces.setdefault((n['hand'], n['t']), []).append(n['chord'])

    for cid, chord in sorted(by_chord.items(), key=lambda x: x[1][0]['t']):
        n0 = chord[0]
        t, h = n0['t'], n0['hand']
        tex = plan.texture_at(t)
        lv = plan.level(t) + plan.pin(t)
        # 6/8 metre: beat one strongest, beat two next
        pos = float(n0['pos'])
        metric = 5 if pos == 0 else 2.5 if pos == 3 else (-1.5 if pos % 1 else 0)
        acc = plan.accents.get(t, 0)
        jitter_t = rnd.gauss(0, 0.004)
        # 8-bar phrase arc
        x = (float(t) % 48) / 48
        arc = 5 * math.sin(math.pi * x) - 2.5 + contour.get(cid, 0.0)
        if tex in ('legg', 'scherz', 'volante', 'scintillante'):
            lv -= 6
        if tex == 'tutti':
            lv += 3
        if tex in ('martellato', 'pesante', 'impeto'):
            lv += 4
        on_base = plan.sec(t) + jitter_t
        if n0['grace']:
            # graces come just before the beat
            seq = graces[(h, t)]
            rank = len(seq) - seq.index(cid)
            on_base = plan.sec(t) - rank * min(0.055, 0.42 * plan.eighth[min(int(t), len(plan.eighth) - 1)])
        dur_s = plan.sec(t + n0['dur']) - plan.sec(t) if n0['dur'] else 0.06
        ar = n0['artic']
        # how long the key is held
        if n0['grace']:
            hold = 0.05
        elif 'staccatissimo' in ar:
            hold = min(dur_s * 0.35, 0.09)
        elif 'staccato' in ar:
            hold = min(dur_s * 0.5, 0.14)
        elif n0['slur'] or n0['stemmed'] or n0['dur'] > 3:
            nx = next_onset(h, t)
            end = plan.sec(nx) + 0.02 if nx is not None and nx <= t + n0['dur'] + F(1, 1000) else plan.sec(t) + dur_s
            hold = max(end - on_base, dur_s * 0.98)
        elif tex in ('legg', 'scherz', 'scintillante', 'volante'):
            hold = dur_s * 0.62
        elif 'tenuto' in ar or 'accent' in ar:
            hold = dur_s * 0.95
        else:
            hold = dur_s * 0.84
        if n0['fermata']:
            hold = max(hold, dur_s * 1.05)
        hold = max(hold, 0.035)
        ps = sorted(chord, key=lambda n: n['pitch'])
        for idx, n in enumerate(ps):
            v = lv + metric + arc + acc
            role = n['role']
            if role == 'top':
                v += 7
            elif role == 'inner':
                v -= 9 if h == 'R' else 11
            elif role == 'bass':
                v += 3
            elif role == 'single' and h == 'L':
                v -= 3
            if 'accent' in ar:
                v += 11
            if 'marcato' in ar:
                v += 15
            if 'staccato' in ar and 'accent' not in ar:
                v -= 3
            if n['small']:
                v -= 9
            if n['grace']:
                v -= 10
            if n['stemmed'] and h == 'R':
                v += 6                    # a melody note that carries its own stem
            v += rnd.gauss(0, 2.2)
            if v > 100:
                v = 100 + (v - 100) * 0.45          # soft knee: keep the loudest chords from clipping
            v = int(max(12, min(120, round(v))))
            on = on_base
            if role == 'top' and n['size'] > 1:
                on -= 0.008               # melody leads the chord slightly
            if n['arp']:
                on += idx * 0.028
            out.append((on, on + hold, n['pitch'], v))
    out.sort()
    pedal = []
    for t, h, mk in marks:
        if mk[0] != 'ped':
            continue
        s = plan.sec(t)
        if mk[1] == 'down':
            pedal.append((s + 0.004, 0))
            pedal.append((s + min(0.09, 0.45 * plan.eighth[min(int(t), len(plan.eighth) - 1)]), 127))
        else:
            pedal.append((s, 0))
    pedal.sort()
    return plan, out, pedal

# ---------------------------------------------------------------- MIDI

def vlq(n):
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.append(0x80 | (n & 0x7F)); n >>= 7
    return bytes(reversed(out))

def chunk(events):
    events.sort(key=lambda e: (e[0], e[1]))
    data, last = bytearray(), 0
    for t, _, b in events:
        data += vlq(t - last) + b; last = t
    data += b'\x00\xff\x2f\x00'
    return b'MTrk' + struct.pack('>I', len(data)) + bytes(data)

def meta(kind, payload):
    return bytes([0xFF, kind]) + vlq(len(payload)) + payload

KEY_NAMES = {-1: (-1, 1), 2: (2, 0), 6: (6, 0)}   # sharps/flats -> (sf, minor?)

def write(path, plan, out, pedal, bars, title):
    cond = [(0, 0, meta(0x03, title.encode('latin-1'))),
            (0, 1, meta(0x58, bytes([6, 3, 24, 8])))]
    last_key = None
    for b in bars:
        if b['key'] != last_key:
            sf, mi = KEY_NAMES.get(b['key'], (b['key'], 0))
            cond.append((b['k'] * 6 * TPE, 2, meta(0x59, struct.pack('>bB', sf, mi))))
            last_key = b['key']
        cond.append((b['k'] * 6 * TPE, 3, meta(0x06, f"m.{b['num']}".encode())))
    last_us = None
    for i, d in enumerate(plan.eighth):
        us = int(round(d * 2 * 1e6))
        if us != last_us:
            cond.append((i * TPE, 4, meta(0x51, us.to_bytes(3, 'big'))))
            last_us = us
    words = []
    for t, h, mk in plan.marks:
        if mk[0] == 'word' and mk[1] not in ('SIGN',):
            words.append((int(t * TPE), 5, meta(0x01, mk[1].encode('latin-1'))))
    cond += words
    piano = [(0, 0, meta(0x03, b'Piano')), (0, 1, bytes([0xB0, 0x00, 0x00])), (0, 2, bytes([0xC0, 0x00])),
             (0, 3, bytes([0xB0, 0x07, 110]))]
    # one key, one sounding note: a re-strike ends the previous one
    evs = []
    for on, off, p, v in out:
        evs.append([on, off, p, v])
    evs.sort()
    by_p = {}
    for e in evs:
        by_p.setdefault(e[2], []).append(e)
    for p, lst in by_p.items():
        for a, b in zip(lst, lst[1:]):
            if a[1] > b[0] - 0.012:
                a[1] = max(a[0] + 0.02, b[0] - 0.012)
    for on, off, p, v in evs:
        t0, t1 = plan.tick(max(0.0, on)), plan.tick(max(0.0, off))
        if t1 <= t0:
            t1 = t0 + 1
        piano.append((t0, 6, bytes([0x90, p, v])))
        piano.append((t1, 5, bytes([0x80, p, 64])))
    for s, val in pedal:
        piano.append((plan.tick(s), 4 if val == 0 else 7, bytes([0xB0, 64, val])))
    end = plan.tick(plan.start[-1]) + PPQ
    piano.append((end, 9, bytes([0xB0, 64, 0])))
    data = b'MThd' + struct.pack('>IHHH', 6, 1, 2, PPQ) + chunk(cond) + chunk(piano)
    with open(path, 'wb') as f:
        f.write(data)

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('brf')
    ap.add_argument('-o', '--out', default='tarantelle.mid')
    ap.add_argument('--tempo', type=float, default=158, help='dotted quarters per minute')
    ap.add_argument('--piu-mosso', type=float, default=0.9, help='eighth-length factor at Più mosso')
    ap.add_argument('--no-repeats', action='store_true', help='skip the two repeats (and first endings)')
    ap.add_argument('--seed', type=int, default=67)
    ap.add_argument('--report', action='store_true', help='print tempo, loudness and markings bar by bar')
    args = ap.parse_args()
    measures, order = build(open(args.brf, encoding='ascii').read())
    if args.no_repeats:
        order = [i for i in range(len(measures)) if not (measures[i]['alt'] is False and
                 i + 1 < len(measures) and measures[i + 1]['alt'])]
    notes, marks, bars = flatten(measures, order)
    plan, out, pedal = render(notes, marks, bars, args)
    write(args.out, plan, out, pedal, bars, 'Gottschalk: Grande Tarantelle, Op. 67 (arr. Espadero)')
    if args.report:
        report(plan, out, marks, bars)
    print(f'{args.out}: {len(bars)} bars, {len(out)} notes, {plan.start[-1]:.1f} s')

def report(plan, out, marks, bars):
    starts = [plan.sec(b['start']) for b in bars] + [plan.start[-1]]
    ons = sorted((on, v) for on, off, p, v in out)
    times = [o[0] for o in ons]
    words = {}
    for t, h, mk in marks:
        if mk[0] == 'word':
            words.setdefault(int(t) // 6, []).append(mk[1])
        elif mk[0] == 'hairpin':
            words.setdefault(int(t) // 6, []).append({'cresc': '<', 'dim': '>'}.get(mk[1], '|'))
    for k, b in enumerate(bars):
        s0, s1 = starts[k], starts[k + 1]
        vs = [v for _, v in ons[bisect.bisect_left(times, s0):bisect.bisect_left(times, s1)]]
        mean = sum(vs) / len(vs) if vs else 0
        print(f"m.{b['num']:<4d}{s0:7.1f}s  q.={120 / (s1 - s0):5.1f}  vel {mean:5.1f} (max {max(vs, default=0):3d})"
              f"  level {plan.level(b['start']):5.1f}  {plan.texture_at(b['start']):12s} {' '.join(words.get(k, []))}")

if __name__ == '__main__':
    main()
