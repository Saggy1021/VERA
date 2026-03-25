# Tailwind CSS Standalone CLI Setup

## Why not the play CDN?
Tailwind's own docs say: "The Play CDN is designed for development only."
It runs JS at runtime (~300KB), is slow, and sends telemetry.
The standalone CLI compiles to a local minified CSS file. No Node.js needed.

## Download

### Linux:
```bash
curl -sLO https://github.com/tailwindlabs/tailwindcss/releases/latest/download/tailwindcss-linux-x64
chmod +x tailwindcss-linux-x64 && mv tailwindcss-linux-x64 tailwindcss
```

### macOS (Apple Silicon):
```bash
curl -sLO https://github.com/tailwindlabs/tailwindcss/releases/latest/download/tailwindcss-macos-arm64
chmod +x tailwindcss-macos-arm64 && mv tailwindcss-macos-arm64 tailwindcss
```

### Windows:
Download `tailwindcss-windows-x64.exe` from GitHub releases.

## Compile
```bash
./tailwindcss -i static/css/input.css -o static/css/vera.css --minify
```

## Development (watch mode)
```bash
./tailwindcss -i static/css/input.css -o static/css/vera.css --watch
```

## After compilation
Prepend the `@font-face` and `@keyframes` from vera-custom.css to vera.css.
Or use a build script:
```bash
cat vera-custom.css > static/css/vera.css
./tailwindcss -i static/css/input.css >> static/css/vera.css --minify
```
