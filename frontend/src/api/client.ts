import axios from 'axios'

const API_URL = (import.meta as any).env?.VITE_API_URL || ''

export const api = axios.create({
  baseURL: `${API_URL}/api/v1`,
  headers: { 'Content-Type': 'application/json' }
})

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('prime_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('prime_token')
      localStorage.removeItem('prime_user')
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
