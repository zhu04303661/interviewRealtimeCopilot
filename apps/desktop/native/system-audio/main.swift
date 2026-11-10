// irc-system-audio — capture what this Mac is playing (all output audio) with
// a Core Audio process tap (macOS 14.2+), and write it to stdout as 16 kHz
// mono PCM16, 100 ms (3,200 bytes) per frame. Status lines go to stderr.
// Exits when stdin closes, so it never outlives the app that started it.
//
// macOS asks once for "System Audio Recording" permission, attributed to the
// app that launched this helper (its Info.plist carries the usage string).
import AudioToolbox
import CoreAudio
import Foundation

func log(_ message: String) { FileHandle.standardError.write(Data((message + "\n").utf8)) }
func fail(_ message: String, _ status: OSStatus = 0) -> Never {
  log("error: \(message)\(status != 0 ? " (OSStatus \(status))" : "")")
  exit(1)
}

func property<T>(_ object: AudioObjectID, _ selector: AudioObjectPropertySelector, _ initial: T) -> (OSStatus, T) {
  var address = AudioObjectPropertyAddress(mSelector: selector, mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
  var value = initial
  var size = UInt32(MemoryLayout<T>.size)
  let status = withUnsafeMutablePointer(to: &value) { AudioObjectGetPropertyData(object, &address, 0, nil, &size, $0) }
  return (status, value)
}

// 1. A private, unmuted tap on everything the system plays.
let tap = CATapDescription(stereoGlobalTapButExcludeProcesses: [])
tap.uuid = UUID()
tap.muteBehavior = .unmuted
tap.isPrivate = true
var tapID = AudioObjectID(kAudioObjectUnknown)
var status = AudioHardwareCreateProcessTap(tap, &tapID)
guard status == noErr else { fail("could not create the audio tap; allow System Audio Recording", status) }

let (formatStatus, format) = property(tapID, kAudioTapPropertyFormat, AudioStreamBasicDescription())
guard formatStatus == noErr, format.mSampleRate > 0 else { fail("could not read the tap format", formatStatus) }

// 2. A private aggregate device that contains the default output device and the tap.
let (outputStatus, outputID) = property(AudioObjectID(kAudioObjectSystemObject), kAudioHardwarePropertyDefaultSystemOutputDevice, AudioDeviceID(0))
guard outputStatus == noErr else { fail("no default output device", outputStatus) }
let (uidStatus, outputUID) = property(outputID, kAudioDevicePropertyDeviceUID, "" as CFString)
guard uidStatus == noErr else { fail("could not read the output device", uidStatus) }

let description: [String: Any] = [
  kAudioAggregateDeviceNameKey: "Interview Realtime Copilot Tap",
  kAudioAggregateDeviceUIDKey: UUID().uuidString,
  kAudioAggregateDeviceMainSubDeviceKey: outputUID as String,
  kAudioAggregateDeviceIsPrivateKey: true,
  kAudioAggregateDeviceIsStackedKey: false,
  kAudioAggregateDeviceTapAutoStartKey: true,
  kAudioAggregateDeviceSubDeviceListKey: [[kAudioSubDeviceUIDKey: outputUID as String]],
  kAudioAggregateDeviceTapListKey: [[kAudioSubTapDriftCompensationKey: true, kAudioSubTapUIDKey: tap.uuid.uuidString]],
]
var aggregateID = AudioObjectID(kAudioObjectUnknown)
status = AudioHardwareCreateAggregateDevice(description as CFDictionary, &aggregateID)
guard status == noErr else { fail("could not create the capture device", status) }

func cleanUp() {
  AudioHardwareDestroyAggregateDevice(aggregateID)
  AudioHardwareDestroyProcessTap(tapID)
}

// 3. Downmix and resample (linear stepping) to 16 kHz PCM16; emit 100 ms frames.
let output = DispatchQueue(label: "irc.system-audio.output")
let step = format.mSampleRate / 16_000.0
var position = 0.0
var pending = [Int16]()
pending.reserveCapacity(3_200)
let isFloat = format.mFormatFlags & kAudioFormatFlagIsFloat != 0

var procID: AudioDeviceIOProcID?
status = AudioDeviceCreateIOProcIDWithBlock(&procID, aggregateID, nil) { _, input, _, _, _ in
  let buffers = UnsafeMutableAudioBufferListPointer(UnsafeMutablePointer(mutating: input))
  guard isFloat, let first = buffers.first, let firstData = first.mData else { return }
  // Interleaved: one buffer with N channels. Non-interleaved: N buffers with one channel each.
  let interleaved = buffers.count == 1
  let channels = interleaved ? max(1, Int(first.mNumberChannels)) : buffers.count
  let frames = Int(first.mDataByteSize) / MemoryLayout<Float32>.size / (interleaved ? channels : 1)
  var chunk = [Int16]()
  while position < Double(frames) {
    let index = Int(position)
    var sum: Float32 = 0
    if interleaved {
      let samples = firstData.assumingMemoryBound(to: Float32.self)
      for c in 0..<channels { sum += samples[index * channels + c] }
    } else {
      for buffer in buffers { if let data = buffer.mData { sum += data.assumingMemoryBound(to: Float32.self)[index] } }
    }
    let mono = max(-1, min(1, sum / Float32(channels)))
    chunk.append(Int16(mono < 0 ? mono * 32_768 : mono * 32_767))
    position += step
  }
  position -= Double(frames)
  output.async {
    pending.append(contentsOf: chunk)
    while pending.count >= 1_600 {
      let frame = pending.prefix(1_600)
      pending.removeFirst(1_600)
      frame.withUnsafeBufferPointer { FileHandle.standardOutput.write(Data(buffer: $0)) }
    }
  }
}
guard status == noErr, let procID else { fail("could not attach the capture callback", status) }
status = AudioDeviceStart(aggregateID, procID)
guard status == noErr else { cleanUp(); fail("could not start capturing", status) }
log("ready \(Int(format.mSampleRate)) Hz, \(format.mChannelsPerFrame) channels")

// 4. Stop when the parent closes stdin (or exits), or on SIGTERM.
func stop() -> Never {
  AudioDeviceStop(aggregateID, procID)
  AudioDeviceDestroyIOProcID(aggregateID, procID)
  cleanUp()
  exit(0)
}
signal(SIGTERM, SIG_IGN)
let terminate = DispatchSource.makeSignalSource(signal: SIGTERM, queue: .main)
terminate.setEventHandler { stop() }
terminate.resume()
DispatchQueue.global().async {
  while !FileHandle.standardInput.availableData.isEmpty {}
  DispatchQueue.main.async { stop() }
}
dispatchMain()
