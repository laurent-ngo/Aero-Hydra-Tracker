#!/bin/bash

# Create the project
npm create vite@latest aero-hydra-ui -- --template react

# Enter the directory
cd aero-hydra-ui

# Install dependencies
npm install --ignore-scripts

# Install the "Adventurer" essentials (Tailwind and Leaflet)
npm install --ignore-scripts -D tailwindcss postcss autoprefixer
npx tailwindcss init -p

npm install --ignore-scripts react-leaflet leaflet lucide-react