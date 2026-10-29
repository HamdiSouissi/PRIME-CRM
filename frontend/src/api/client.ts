import axios from 'axios'

export function apiUrls(apiOrigin: string) {
  const origin = apiOrigin.replace(/\/+$/, '')
  return { api: `${origin}/api/v1`, docs: `${origin}/docs` }
}

const urls = apiUrls((import.meta as any).env?.VITE_API_URL || '')
// With a separate static frontend, documentation is served by the API host.
export const API_DOCS_URL = urls.docs

export const api = axios.create({
  baseURL: urls.api,
  headers: { 'Content-Type': 'application/json' }
})

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('prime_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  else delete config.headers.Authorization // another tab may have signed out
  return config
})

api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      clearAuth()
      if (window.location.pathname !== '/login') window.location.href = '/login'
    }
    return Promise.reject(err)
  }
)

export function setAuthToken(token: string) {
  localStorage.setItem('prime_token', token)
  api.defaults.headers.common['Authorization'] = `Bearer ${token}`
}
export function clearAuth() {
  localStorage.removeItem('prime_token')
  localStorage.removeItem('prime_user')
  delete api.defaults.headers.common['Authorization']
}
