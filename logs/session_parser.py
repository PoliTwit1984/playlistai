import json

# Load the JSON file
with open('s.json', 'r') as file:
    data = json.load(file)

# Extract song details
songs = []
for track_info in data['recent_tracks']:
    track = track_info['track']
    song = {
        "name": track['name'],
        "artist": ", ".join(artist['name'] for artist in track['artists']),
        "genre": "Unknown"  # The genre is not directly listed in this structure
    }
    songs.append(song)

# Print the extracted songs
for song in songs:
    print(f"Song: {song['name']}, Artist: {song['artist']}, Genre: {song['genre']}")