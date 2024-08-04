# MoodWave Application Flow

## High-Level Overview

1. User arrives at the MoodWave website
2. User logs in with Spotify
3. User fills out initial preferences form
4. User reviews and confirms preferences
5. Application generates a personalized playlist
6. User previews the generated playlist

## Detailed Flow Analysis

### 1. User Arrival and Authentication

- User navigates to the MoodWave homepage (`/` route)
- If not logged in, user is prompted to log in with Spotify
- Clicking "Login with Spotify" redirects to Spotify's OAuth page
- After successful authentication, Spotify redirects back to MoodWave (`/redirect` route)
- The application stores the Spotify access token in the session

### 2. Initial Preferences Form

- User is presented with the initial preferences form (`/initial_form` route)
- Form fields include:
  - Activity
  - Energy Level
  - Current Mood
  - Desired Mood
  - Discovery Level
  - Time of Day
  - Duration
  - Favorite Artists
  - Favorite Genres
  - Playlist Description
- User fills out the form and submits

### 3. Preferences Review and Confirmation

- Application processes the form data (`/initial_form` POST handler)
- User is redirected to review preferences (`/load_user_preferences` route)
- `get_user_profile(sp)` is called to fetch the user's Spotify profile
- `get_user_top_artists(sp, limit=10)` and `get_user_top_genres(sp, limit=10)` are called to fetch user's top artists and genres
- `get_playlist_picks(sp, limit=20)` is called to get tracks from user's playlists
- `get_wayback_tracks(sp, limit=20)` is called to get tracks from user's library history
- User reviews preferences and selected tracks
- User confirms preferences, which are stored in the session

### 4. Playlist Generation

- User triggers playlist generation (`/generate_playlist` route)
- Application retrieves user preferences and confirmed selections from the session
- `get_expanded_track_pool(sp, selected_artists, selected_genres, user_profile, discovery_ratio)` is called:
  - Calls `get_tracks_from_favorites(sp, favorite_artists, favorite_genres)`
  - Calls `get_user_top_and_recent_tracks(sp)`
  - Calls `get_new_releases(sp)`
  - Calls `get_new_artist_tracks(sp)`
  - For each track, calls `analyze_audio_features(audio_features)` to get detailed audio analysis
  - Returns familiar_tracks and discovery_tracks
- Application combines and deduplicates tracks, limiting to 200 while maintaining the discovery ratio
- `get_openai_recommendations(client, user_preferences, all_tracks, num_tracks)` is called:
  - Sends a detailed prompt to OpenAI with user preferences and track information
  - Returns a JSON response with recommended tracks and explanations
- `parse_openai_response(openai_response)` is called to extract:
  - recommended_tracks
  - ai_playlist_description
  - explanation
- `find_tracks_on_spotify(sp, recommended_tracks)` is called to get Spotify track IDs for the recommended tracks

### 5. Playlist Preview

- Application stores the generated playlist information in the session:
  - recommended_tracks
  - ai_playlist_description
  - explanation
  - spotify_track_ids
- Renders the `playlist_preview.html` template with the playlist information

## Key Functions and Their Interactions

1. `get_spotify_client()`:
   - Returns an authenticated Spotify client object
   - Used throughout the application for Spotify API calls

2. `get_expanded_track_pool(sp, favorite_artists, favorite_genres, user_profile, discovery_ratio)`:
   - Calls multiple helper functions to gather tracks
   - Calls `analyze_audio_features(audio_features)` for each track
   - Calls `calculate_discovery_score(track, user_profile, sp)` for each track
   - Returns familiar_tracks and discovery_tracks

3. `analyze_audio_features(audio_features)`:
   - Takes Spotify audio features as input
   - Returns a dictionary with detailed analysis including mood scores, suitable activities, best time of day, etc.

4. `get_openai_recommendations(client, user_preferences, tracks, num_tracks)`:
   - Takes OpenAI client, user preferences, and track pool as input
   - Sends a detailed prompt to OpenAI
   - Returns OpenAI's response with playlist recommendations

5. `parse_openai_response(response)`:
   - Takes the raw OpenAI response
   - Extracts and returns recommended_tracks, ai_playlist_description, and explanation

6. `find_tracks_on_spotify(sp, recommended_tracks)`:
   - Takes Spotify client and recommended tracks
   - Searches for each track on Spotify
   - Returns a list of Spotify track IDs

This flow represents the core functionality of the MoodWave application, from user input to playlist generation and preview. Each step builds on the previous ones, utilizing various API integrations and data processing techniques to create a personalized playlist experience.