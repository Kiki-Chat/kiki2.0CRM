# ---- build stage: compile the Vite SPA ----
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
# npm install (not ci) — the committed lockfile is out of sync with package.json
RUN npm install --no-audit --no-fund
COPY . .
# Public build-time config — Vite inlines VITE_* at build time. Defaults target prod;
# Railway can override via service build args. (Anon key is the publishable key.)
ARG VITE_API_URL=https://api.kikichat.de
ARG VITE_SUPABASE_URL=https://ifbluvdcbcesuhvkxsfn.supabase.co
ARG VITE_SUPABASE_ANON_KEY=sb_publishable_j2SeGLjSYz5NZdCzBrF6Jw_VLJq466Q
# Kiki copilot widget — on by default for prod builds; Railway can override the
# VITE_COPILOT_ENABLED service build arg to '0' to ship it hidden.
ARG VITE_COPILOT_ENABLED=1
# Optional: pin the Supabase auth redirect (password recovery / magic-link) to a
# fixed host. Left BLANK so it follows window.location.origin — i.e. whatever
# domain the SPA is served from (crm.kikichat.de today, crm.heykiki.de later) —
# with no rebuild needed on a domain change. Set it only to FORCE a canonical host.
ARG VITE_PUBLIC_APP_URL=
RUN printf 'VITE_API_URL=%s\nVITE_SUPABASE_URL=%s\nVITE_SUPABASE_ANON_KEY=%s\nVITE_COPILOT_ENABLED=%s\nVITE_PUBLIC_APP_URL=%s\n' \
      "$VITE_API_URL" "$VITE_SUPABASE_URL" "$VITE_SUPABASE_ANON_KEY" "$VITE_COPILOT_ENABLED" "$VITE_PUBLIC_APP_URL" > .env.production \
  && npm run build

# ---- serve stage: static SPA on $PORT ----
FROM node:22-alpine AS serve
WORKDIR /app
RUN npm install -g serve@14
COPY --from=build /app/dist ./dist
ENV PORT=8080
EXPOSE 8080
CMD ["sh", "-c", "serve -s dist -l ${PORT}"]
