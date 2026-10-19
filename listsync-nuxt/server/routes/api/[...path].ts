/**
 * Same-origin API proxy with server-side bearer injection.
 *
 * The browser only ever calls `/api/**` on the Nuxt origin. This handler
 * forwards the request to the FastAPI backend and, when
 * `LISTS_SYNC_API_TOKEN` is configured, adds the bearer token here — so the
 * token is never shipped to or readable by the browser.
 */

import { defineEventHandler, getRequestURL, proxyRequest } from 'h3'

function backendBase(): string {
  return (process.env.LISTS_SYNC_API_URL || 'http://127.0.0.1:4222').replace(/\/+$/, '')
}

export default defineEventHandler((event) => {
  const url = getRequestURL(event)
  const target = `${backendBase()}${url.pathname}${url.search}`

  const token = (process.env.LISTS_SYNC_API_TOKEN || '').trim()
  if (token) {
    event.node.req.headers.authorization = `Bearer ${token}`
  } else {
    // Never forward an Authorization header supplied by the browser.
    delete event.node.req.headers.authorization
  }

  return proxyRequest(event, target)
})
