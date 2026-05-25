# ---- build stage: compile the Vite SPA ----
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
# npm install (not ci) — the committed lockfile is out of sync with package.json
RUN npm install --no-audit --no-fund
COPY . .
# Public build-time config — Vite inlines VITE_* at build time. Defaults target prod;
# Railway can override via service build args. (Anon key is the publishable key.)
ARG VITE_API_URL=https://backend-production-3f88a.up.railway.app
ARG VITE_SUPABASE_URL=https://ifbluvdcbcesuhvkxsfn.supabase.co
ARG VITE_SUPABASE_ANON_KEY=sb_publishable_j2SeGLjSYz5NZdCzBrF6Jw_VLJq466Q
RUN printf 'VITE_API_URL=%s\nVITE_SUPABASE_URL=%s\nVITE_SUPABASE_ANON_KEY=%s\n' \
      "$VITE_API_URL" "$VITE_SUPABASE_URL" "$VITE_SUPABASE_ANON_KEY" > .env.production \
  && npm run build

# ---- serve stage: static SPA on $PORT ----
FROM node:22-alpine AS serve
WORKDIR /app
RUN npm install -g serve@14
COPY --from=build /app/dist ./dist
ENV PORT=8080
EXPOSE 8080
CMD ["sh", "-c", "serve -s dist -l ${PORT}"]
