import { createError, defineEventHandler, sendRedirect } from 'h3'
import { isPublicPath, resolveAuth, safeRedirect } from '../utils/auth'

export default defineEventHandler(async (event) => {
  const pathname = event.path.split('?')[0] || '/'
  if (isPublicPath(pathname)) {
    return
  }

  const auth = await resolveAuth(event)
  if (auth.authenticated) {
    return
  }

  const unauthorized = auth.reason === 'not_allowed' ? 403 : 401
  if (pathname.startsWith('/api/')) {
    throw createError({
      statusCode: unauthorized,
      statusMessage: auth.reason === 'not_allowed' ? 'Email not allowed' : 'Authentication required',
    })
  }

  const params = new URLSearchParams()
  const redirect = safeRedirect(event.path)
  if (redirect !== '/') {
    params.set('redirect', redirect)
  }
  if (auth.reason === 'not_allowed') {
    params.set('error', 'not_allowed')
  }
  const suffix = params.size ? `?${params.toString()}` : ''
  return sendRedirect(event, `/login${suffix}`)
})
