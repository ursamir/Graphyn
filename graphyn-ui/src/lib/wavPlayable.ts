/**
 * Ensure a WAV blob is Chromium-playable.
 * Pipeline dumps often use IEEE float32 (format 3); browsers only decode PCM (1).
 */

const RIFF = 0x46464952
const WAVE = 0x45564157
const FMT = 0x20746d66
const DATA = 0x61746164

function readU16(view: DataView, o: number) {
  return view.getUint16(o, true)
}
function readU32(view: DataView, o: number) {
  return view.getUint32(o, true)
}
function writeU16(view: DataView, o: number, v: number) {
  view.setUint16(o, v, true)
}
function writeU32(view: DataView, o: number, v: number) {
  view.setUint32(o, v, true)
}

type WavInfo = {
  audioFormat: number
  numChannels: number
  sampleRate: number
  bitsPerSample: number
  dataOffset: number
  dataSize: number
}

function parseWav(buf: ArrayBuffer): WavInfo | null {
  if (buf.byteLength < 44) return null
  const view = new DataView(buf)
  if (readU32(view, 0) !== RIFF || readU32(view, 8) !== WAVE) return null

  let offset = 12
  let audioFormat = 0
  let numChannels = 0
  let sampleRate = 0
  let bitsPerSample = 0
  let dataOffset = -1
  let dataSize = 0

  while (offset + 8 <= view.byteLength) {
    const id = readU32(view, offset)
    const size = readU32(view, offset + 4)
    const body = offset + 8
    if (id === FMT && size >= 16) {
      audioFormat = readU16(view, body)
      numChannels = readU16(view, body + 2)
      sampleRate = readU32(view, body + 4)
      bitsPerSample = readU16(view, body + 14)
    } else if (id === DATA) {
      dataOffset = body
      dataSize = size
      break
    }
    offset = body + size + (size % 2)
  }

  if (!audioFormat || !numChannels || !sampleRate || !bitsPerSample || dataOffset < 0) return null
  return { audioFormat, numChannels, sampleRate, bitsPerSample, dataOffset, dataSize }
}

function encodePcm16Wav(
  samples: Int16Array,
  numChannels: number,
  sampleRate: number,
): ArrayBuffer {
  const dataSize = samples.byteLength
  const out = new ArrayBuffer(44 + dataSize)
  const view = new DataView(out)
  writeU32(view, 0, RIFF)
  writeU32(view, 4, 36 + dataSize)
  writeU32(view, 8, WAVE)
  writeU32(view, 12, FMT)
  writeU32(view, 16, 16)
  writeU16(view, 20, 1) // PCM
  writeU16(view, 22, numChannels)
  writeU32(view, 24, sampleRate)
  writeU32(view, 28, sampleRate * numChannels * 2)
  writeU16(view, 32, numChannels * 2)
  writeU16(view, 34, 16)
  writeU32(view, 36, DATA)
  writeU32(view, 40, dataSize)
  new Uint8Array(out, 44).set(new Uint8Array(samples.buffer, samples.byteOffset, samples.byteLength))
  return out
}

function floatToPcm16(floats: Float32Array): Int16Array {
  const out = new Int16Array(floats.length)
  for (let i = 0; i < floats.length; i++) {
    const s = Math.max(-1, Math.min(1, floats[i]))
    out[i] = s < 0 ? (s * 0x8000) | 0 : (s * 0x7fff) | 0
  }
  return out
}

/**
 * Return a blob URL suitable for &lt;audio&gt;. Converts IEEE-float WAV → 16-bit PCM.
 * Caller must revoke the URL. Returns null if the buffer is not a WAV we can handle
 * (caller should fall back to the original blob URL).
 */
export function wavBufferToPlayableObjectUrl(buf: ArrayBuffer): string | null {
  const info = parseWav(buf)
  if (!info) return null

  // Already browser-friendly PCM 8/16-bit.
  if (info.audioFormat === 1 && (info.bitsPerSample === 8 || info.bitsPerSample === 16)) {
    return URL.createObjectURL(new Blob([buf], { type: 'audio/wav' }))
  }

  // IEEE float (3) — common from numpy / torch audio dumps.
  if (info.audioFormat === 3 && info.bitsPerSample === 32) {
    const end = Math.min(info.dataOffset + info.dataSize, buf.byteLength)
    const byteLen = end - info.dataOffset
    const aligned = byteLen - (byteLen % 4)
    if (aligned < 4) return null
    const floats = new Float32Array(buf.slice(info.dataOffset, info.dataOffset + aligned))
    const pcm = floatToPcm16(floats)
    const encoded = encodePcm16Wav(pcm, info.numChannels, info.sampleRate)
    return URL.createObjectURL(new Blob([encoded], { type: 'audio/wav' }))
  }

  // 24-bit / 32-bit PCM — downsample to 16-bit.
  if (info.audioFormat === 1 && info.bitsPerSample === 32) {
    const end = Math.min(info.dataOffset + info.dataSize, buf.byteLength)
    const byteLen = end - info.dataOffset
    const aligned = byteLen - (byteLen % 4)
    if (aligned < 4) return null
    const i32 = new Int32Array(buf.slice(info.dataOffset, info.dataOffset + aligned))
    const pcm = new Int16Array(i32.length)
    for (let i = 0; i < i32.length; i++) pcm[i] = i32[i] >> 16
    const encoded = encodePcm16Wav(pcm, info.numChannels, info.sampleRate)
    return URL.createObjectURL(new Blob([encoded], { type: 'audio/wav' }))
  }

  return null
}
