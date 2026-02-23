FROM node:20-alpine

WORKDIR /app

# Install dependencies first for layer caching
COPY package.json package-lock.json* ./
RUN npm install

# Copy source code (mounted over in dev via docker-compose)
COPY . .

EXPOSE 3000

CMD ["npm", "run", "dev"]
