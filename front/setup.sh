#!/bin/bash

# Create the project
npm create vite@latest aero-hydra-ui -- --template react

# Enter the directory
cd aero-hydra-ui

# Install dependencies
npm install

# Install the "Adventurer" essentials (Tailwind and Leaflet)
npm install -D tailwindcss postcss autoprefixer
npx tailwindcss init -p

npm install react-leaflet leaflet lucide-react