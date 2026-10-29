FROM node:24-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# Public origin only; never pass credentials to a browser build.
ARG VITE_API_URL
RUN npm run build

# The release preview uses this isolated stage before packaging static files.
# No Netlify token is passed to the image or its build commands.
FROM build AS verified-static
# Tests use mocked APIs and must not point at the live backend.
RUN npm run lint && VITE_API_URL= npm run test -- --run

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD wget -qO- http://localhost/ || exit 1
CMD ["nginx", "-g", "daemon off;"]
