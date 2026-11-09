// Converts captured audio to 16 kHz mono PCM16 and posts 100 ms frames.
class PcmFrames extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / 16000;
    this.position = 0;
    this.frame = new Int16Array(1600);
    this.filled = 0;
  }
  process(inputs) {
    const channels = inputs[0];
    if (!channels || channels.length === 0) return true;
    const length = channels[0].length;
    for (; this.position < length; this.position += this.ratio) {
      const index = Math.floor(this.position);
      let sample = 0;
      for (const channel of channels) sample += channel[index];
      sample = Math.max(-1, Math.min(1, sample / channels.length));
      this.frame[this.filled++] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
      if (this.filled === this.frame.length) {
        this.port.postMessage(this.frame.buffer, [this.frame.buffer]);
        this.frame = new Int16Array(1600);
        this.filled = 0;
      }
    }
    this.position -= length;
    return true;
  }
}
registerProcessor('pcm-frames', PcmFrames);
