FROM node:22-alpine AS base

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm install

COPY . .

FROM base AS dev

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]

FROM base AS build

ARG VITE_API_URL=http://127.0.0.1:8000
ENV VITE_API_URL=${VITE_API_URL}

RUN npm run build

FROM node:22-alpine AS prod

WORKDIR /app

RUN npm install -g serve

COPY --from=build /app/dist ./dist

EXPOSE 4173

CMD ["sh", "-c", "serve -s dist -l ${PORT:-4173}"]
