FROM rust:1.83-slim AS builder

WORKDIR /app
COPY . .
RUN cargo build --release -p workers-spec-cli

FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y ca-certificates && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/target/release/workers-spec /usr/local/bin/

ENV PORT=3005
ENV DATABASE_PATH=/data/workers-spec.db
EXPOSE 3005

VOLUME ["/data"]

CMD ["workers-spec", "serve", "--port", "3005", "--database-path", "/data/workers-spec.db"]
