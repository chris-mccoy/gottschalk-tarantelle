// SPDX-License-Identifier: MIT
// render.swift -- play a MIDI file through a macOS sampler instrument, offline, into an audio file.
//
// usage: swift render.swift IN.mid OUT.m4a [SOUNDBANK.sf2|.dls | INSTRUMENT.exs|.aupreset]
//
// The default is the acoustic grand (program 0) of the General MIDI bank built into macOS.
// GarageBand's Steinway (an EXS24 instrument over one consolidated .caf) will not load into
// AVAudioUnitSampler, so for that sound open the MIDI file in GarageBand instead.  The MIDI
// file's tempo map is honoured (AudioToolbox converts every event to seconds), the sustain
// pedal is passed on, a little hall reverb is added, and the result is normalised to -1 dBFS.
import AVFoundation
import AudioToolbox

let args = CommandLine.arguments
guard args.count >= 3 else {
    FileHandle.standardError.write("usage: swift render.swift IN.mid OUT.m4a [INSTRUMENT]\n".data(using: .utf8)!)
    exit(2)
}
let midURL = URL(fileURLWithPath: args[1])
let outURL = URL(fileURLWithPath: args[2])
let instrument = args.count > 3 ? args[3]
    : "/System/Library/Components/CoreAudio.component/Contents/Resources/gs_instruments.dls"
let sampleRate = 44100.0
let block = 64                                   // events land on 64-frame (1.5 ms) boundaries

// ---- the events, in seconds
struct Event { var t: Double; var kind: Int; var a: UInt8; var b: UInt8 }    // kind 0 off, 1 on, 2 controller
var events: [Event] = []
var seqOpt: MusicSequence?
NewMusicSequence(&seqOpt)
let seq = seqOpt!
guard MusicSequenceFileLoad(seq, midURL as CFURL, .midiType, MusicSequenceLoadFlags()) == noErr else {
    fatalError("cannot read \(midURL.path)")
}
var trackCount: UInt32 = 0
MusicSequenceGetTrackCount(seq, &trackCount)
func seconds(_ beat: MusicTimeStamp) -> Double {
    var s: Float64 = 0
    MusicSequenceGetSecondsForBeats(seq, beat, &s)
    return s
}
for i in 0..<trackCount {
    var track: MusicTrack?
    MusicSequenceGetIndTrack(seq, i, &track)
    var it: MusicEventIterator?
    NewMusicEventIterator(track!, &it)
    var has: DarwinBoolean = false
    MusicEventIteratorHasCurrentEvent(it!, &has)
    while has.boolValue {
        var beat: MusicTimeStamp = 0
        var type: MusicEventType = 0
        var data: UnsafeRawPointer?
        var size: UInt32 = 0
        MusicEventIteratorGetEventInfo(it!, &beat, &type, &data, &size)
        if type == kMusicEventType_MIDINoteMessage {
            let m = data!.load(as: MIDINoteMessage.self)
            events.append(Event(t: seconds(beat), kind: 1, a: m.note, b: m.velocity))
            events.append(Event(t: seconds(beat + MusicTimeStamp(m.duration)), kind: 0, a: m.note, b: 0))
        } else if type == kMusicEventType_MIDIChannelMessage {
            let m = data!.load(as: MIDIChannelMessage.self)
            if m.status & 0xF0 == 0xB0 {
                events.append(Event(t: seconds(beat), kind: 2, a: m.data1, b: m.data2))
            }
        }
        MusicEventIteratorNextEvent(it!)
        MusicEventIteratorHasCurrentEvent(it!, &has)
    }
}
events.sort { $0.t != $1.t ? $0.t < $1.t : $0.kind < $1.kind }      // a release before a strike
let end = (events.last?.t ?? 0) + 4.0                                 // let the last chord ring

// ---- the engine: sampler -> reverb -> output, rendered offline
let engine = AVAudioEngine()
let sampler = AVAudioUnitSampler()
let reverb = AVAudioUnitReverb()
reverb.loadFactoryPreset(.mediumHall)
reverb.wetDryMix = 18
engine.attach(sampler)
engine.attach(reverb)
engine.connect(sampler, to: reverb, format: nil)
engine.connect(reverb, to: engine.mainMixerNode, format: nil)
do {
    let url = URL(fileURLWithPath: instrument)
    if ["dls", "sf2"].contains(url.pathExtension.lowercased()) {
        try sampler.loadSoundBankInstrument(at: url, program: 0, bankMSB: UInt8(kAUSampler_DefaultMelodicBankMSB),
                                            bankLSB: UInt8(kAUSampler_DefaultBankLSB))
    } else {
        try sampler.loadInstrument(at: url)
    }
} catch {
    fatalError("cannot load instrument \(instrument): \(error)")
}
let format = AVAudioFormat(standardFormatWithSampleRate: sampleRate, channels: 2)!
try! engine.enableManualRenderingMode(.offline, format: format, maximumFrameCount: AVAudioFrameCount(block))
try! engine.start()

let total = Int(end * sampleRate)
var left = [Float](repeating: 0, count: total)
var right = [Float](repeating: 0, count: total)
let buffer = AVAudioPCMBuffer(pcmFormat: engine.manualRenderingFormat, frameCapacity: AVAudioFrameCount(block))!
var next = 0
var frame = 0
while frame < total {
    let now = Double(frame) / sampleRate
    while next < events.count && events[next].t <= now {
        let e = events[next]
        switch e.kind {
        case 0: sampler.stopNote(e.a, onChannel: 0)
        case 1: sampler.startNote(e.a, withVelocity: e.b, onChannel: 0)
        default: sampler.sendController(e.a, withValue: e.b, onChannel: 0)
        }
        next += 1
    }
    let n = min(block, total - frame)
    let status = try! engine.renderOffline(AVAudioFrameCount(n), to: buffer)
    guard status == .success else { fatalError("render failed: \(status.rawValue)") }
    let l = buffer.floatChannelData![0], r = buffer.floatChannelData![1]
    for j in 0..<Int(buffer.frameLength) {
        left[frame + j] = l[j]
        right[frame + j] = r[j]
    }
    frame += n
}
engine.stop()

// ---- normalise and write
var peak: Float = 1e-9
for j in 0..<total { peak = max(peak, abs(left[j]), abs(right[j])) }
let gain = Float(pow(10.0, -1.0 / 20.0)) / peak
let chunk = 8192
let settings: [String: Any] = [AVFormatIDKey: kAudioFormatMPEG4AAC, AVSampleRateKey: sampleRate,
                               AVNumberOfChannelsKey: 2, AVEncoderBitRateKey: 256_000]
let file = try! AVAudioFile(forWriting: outURL, settings: settings, commonFormat: .pcmFormatFloat32, interleaved: false)
let out = AVAudioPCMBuffer(pcmFormat: AVAudioFormat(standardFormatWithSampleRate: sampleRate, channels: 2)!,
                           frameCapacity: AVAudioFrameCount(chunk))!
var pos = 0
while pos < total {
    let n = min(chunk, total - pos)
    for j in 0..<n {
        out.floatChannelData![0][j] = left[pos + j] * gain
        out.floatChannelData![1][j] = right[pos + j] * gain
    }
    out.frameLength = AVAudioFrameCount(n)
    try! file.write(from: out)
    pos += n
}
file.close()                                     // finalises the .m4a (globals are never deinitialised)
print(String(format: "%@: %.1f s, peak %.2f before normalising", outURL.lastPathComponent, end, peak))
