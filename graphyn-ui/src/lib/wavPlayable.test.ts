import { describe, expect, it } from 'vitest'
import { wavBufferToPlayableObjectUrl } from './wavPlayable'

function writeU16(view: DataView, o: number, v: number) {
  view.setUint16(o, v, true)
}
function writeU32(view: DataView, o: number, v: number) {
  view.setUint32(o, v, true)
}

function makeFloat32Wav(samples: number[], sampleRate = 16000, channels = 1): ArrayBuffer {
  const dataSize = samples.length * 4
  const buf = new ArrayBuffer(44 + dataSize)
  const view = new DataView(buf)
  writeU32(view, 0, 0x46464952) // RIFF
  writeU32(view, 4, 36 + dataSize)
  writeU32(view, 8, 0x45564157) // WAVE
  writeU32(view, 12, 0x20746d66) // fmt
  writeU32(view, 16, 16)
  writeU16(view, 20, 3) // IEEE float
  writeU16(view, 22, channels)
  writeU32(view, 24, sampleRate)
  writeU32(view, 28, sampleRate * channels * 4)
  writeU16(view, 32, channels * 4)
  writeU16(view, 34, 32)
  writeU32(view, 36, 0x61746164) // data
  writeU32(view, 40, dataSize)
  const f32 = new Float32Array(buf, 44, samples.length)
  f32.set(samples)
  return buf
}

describe('wavBufferToPlayableObjectUrl', () => {
  it('converts IEEE float32 WAV to a playable blob URL', () => {
    const buf = makeFloat32Wav([0, 0.5, -0.5, 1, -1])
    const url = wavBufferToPlayableObjectUrl(buf)
    expect(url).toMatch(/^blob:/)
    URL.revokeObjectURL(url!)
  })

  it('returns null for non-WAV buffers', () => {
    expect(wavBufferToPlayableObjectUrl(new ArrayBuffer(8))).toBeNull()
  })
})
