FROM golang:1.27.4-alpine AS build

WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download

COPY . .
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/listsync ./cmd/listsync

FROM gcr.io/distroless/static-debian12:nonroot

WORKDIR /app
COPY --from=build /out/listsync /usr/local/bin/listsync

EXPOSE 4222
USER nonroot:nonroot
ENTRYPOINT ["/usr/local/bin/listsync"]
