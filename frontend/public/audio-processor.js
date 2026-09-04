class AudioProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.bufferSize = 4096;
    this.buffer = new Float32Array(this.bufferSize);
    this.bufferIndex = 0;

    // 监听stop消息，flush剩余数据
    this.port.onmessage = (event) => {
      if (event.data.type === 'stop' && this.bufferIndex > 0) {
        this.port.postMessage({
          type: 'audioData',
          audioData: this.buffer.slice(0, this.bufferIndex)
        });
      }
    };
  }

  process(inputs, outputs, parameters) {
    const input = inputs[0];
    if (input && input.length > 0) {
      const inputData = input[0];

      for (let i = 0; i < inputData.length; i++) {
        this.buffer[this.bufferIndex] = inputData[i];
        this.bufferIndex++;

        if (this.bufferIndex >= this.bufferSize) {
          // 发送音频数据到主线程
          this.port.postMessage({
            type: 'audioData',
            audioData: this.buffer.slice()
          });
          this.bufferIndex = 0;
        }
      }
    }

    return true;
  }
}

registerProcessor('audio-processor', AudioProcessor);
