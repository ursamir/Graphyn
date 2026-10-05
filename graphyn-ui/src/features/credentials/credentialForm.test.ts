import { describe, expect, it } from 'vitest'
import {
  buildPayload,
  fieldChoices,
  fieldHint,
  fieldInput,
  fieldLabel,
  fieldVisible,
  hasFormFields,
  initialFormValues,
  missingRequired,
  parsePayloadJson,
  valuesFromPayload,
  type KindInfo,
} from './credentialForm'

const openai: KindInfo = {
  id: 'openai_compat',
  label: 'OpenAI-compatible',
  fields: [
    { name: 'api_key', secret: true, required: true, description: 'API key' },
    { name: 'base_url', secret: false, required: false, description: 'Optional base URL', default: '' },
    { name: 'default_model', secret: false, required: false, description: 'Optional default model', default: '' },
  ],
}

const smtp: KindInfo = {
  id: 'smtp',
  label: 'SMTP',
  fields: [
    { name: 'host', secret: false, required: true, description: 'SMTP host' },
    { name: 'port', secret: false, required: false, description: 'SMTP port', default: 587 },
    { name: 'password', secret: true, required: false, description: 'SMTP password', default: '' },
    { name: 'tls', secret: false, required: false, description: 'STARTTLS', default: true },
  ],
}

describe('credentialForm', () => {
  it('labels known and unknown fields', () => {
    expect(fieldLabel('api_key')).toBe('API key')
    expect(fieldLabel('base_url')).toBe('Base URL')
    expect(fieldLabel('default_model')).toBe('Default model')
    expect(fieldLabel('org_id')).toBe('Org ID')
    expect(fieldLabel('region')).toBe('Region')
  })

  it('derives input types from secret flag and default type', () => {
    expect(fieldInput(openai.fields[0])).toBe('password')
    expect(fieldInput(openai.fields[1])).toBe('text')
    expect(fieldInput(smtp.fields[1])).toBe('number')
    expect(fieldInput(smtp.fields[3])).toBe('checkbox')
  })

  it('drops hints that only repeat the label', () => {
    expect(fieldHint(openai.fields[0])).toBe('')
    expect(fieldHint(openai.fields[1])).toBe('')
    expect(fieldHint(smtp.fields[0])).toBe('SMTP host')
  })

  it('initial values and payload round-trip', () => {
    const v = initialFormValues(smtp)
    expect(v).toEqual({ host: '', port: '587', password: '', tls: true })
    expect(missingRequired(smtp, v)).toEqual(['Host'])
    v.host = ' mail.example.com '
    expect(missingRequired(smtp, v)).toEqual([])
    expect(buildPayload(smtp, v)).toEqual({ host: 'mail.example.com', port: 587, tls: true })
  })

  it('omits empty optional fields; keeps secret whitespace verbatim', () => {
    const v = initialFormValues(openai)
    v.api_key = 'sk-abc '
    expect(buildPayload(openai, v)).toEqual({ api_key: 'sk-abc ' })
  })

  it('valuesFromPayload fills known fields only', () => {
    const v = valuesFromPayload(smtp, { host: 'h', port: 25, tls: false, extra: 1 })
    expect(v).toEqual({ host: 'h', port: '25', password: '', tls: false })
  })

  it('hasFormFields + parsePayloadJson', () => {
    expect(hasFormFields(undefined)).toBe(false)
    expect(hasFormFields({ id: 'x', label: 'x', fields: [] })).toBe(false)
    expect(hasFormFields(openai)).toBe(true)
    expect(parsePayloadJson('{"a":1}')).toEqual({ payload: { a: 1 } })
    expect(parsePayloadJson('')).toEqual({ payload: {} })
    expect('error' in parsePayloadJson('[1]')).toBe(true)
    expect('error' in parsePayloadJson('{')).toBe(true)
  })
})

describe('http_auth kind form', () => {
  const httpAuth: KindInfo = {
    id: 'http_auth',
    label: 'HTTP auth',
    fields: [
      { name: 'scheme', secret: false, required: true, description: 'bearer | basic | header', default: 'bearer' },
      { name: 'token', secret: true, required: false, description: 'Bearer token (scheme=bearer)', default: '' },
      { name: 'username', secret: false, required: false, description: 'Username (scheme=basic)', default: '' },
      { name: 'password', secret: true, required: false, description: 'Password (scheme=basic)', default: '' },
      { name: 'allowed_hosts', secret: false, required: false, description: 'Optional CSV of hostnames', default: '' },
    ],
  }
  it('renders enumerated descriptions as choices and hides other-scheme fields', () => {
    expect(fieldChoices(httpAuth.fields[0])).toEqual(['bearer', 'basic', 'header'])
    expect(fieldChoices(httpAuth.fields[1])).toBeNull()
    const values = { ...initialFormValues(httpAuth), scheme: 'basic', token: 'leftover', username: 'u', password: 'p' }
    expect(httpAuth.fields.filter((f) => fieldVisible(f, values)).map((f) => f.name)).toEqual([
      'scheme',
      'username',
      'password',
      'allowed_hosts',
    ])
    expect(buildPayload(httpAuth, values)).toEqual({ scheme: 'basic', username: 'u', password: 'p' })
    expect(fieldHint(httpAuth.fields[1])).toBe('Bearer token')
  })
})
