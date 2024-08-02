# Process Breakdown for generate_playlist Function

## User Arrives at initial_form:

The user is presented with a form containing the following fields:
- **Name** (optional text field)
- **Mood** (slider or selection, range TBD)
- **Desired Mood** (slider or selection, range TBD)
- **Activity** (free text field)
- **Energy Level** (slider, 0-100)
- **Time of Day** (dropdown: Morning, Afternoon, Evening, Night)
- **Duration** (number input, in minutes)
- **Discovery Level** (slider, 0-100)
- **Favorite Artists** (text field, comma-separated)
- **Favorite Genres** (text field, comma-separated)
- **Playlist Description** (text area)

## User Submits initial_form:

1. **POST request** is sent to the `/initial_form` route
2. **Server-side validation** occurs in the `initial_form()` function
    - If validation fails, user is returned to the form with error messages
    - If validation passes, form data is stored in the session as 'form_data'
3. User is redirected to `/load_user_preferences` route

## load_user_preferences Route:

1. Retrieves Spotify client using `get_spotify_client()`
    - If Spotify client is not available, redirects to login
2. Calls the following functions to gather user data:
    - `get_user_profile(sp)`
    - `get_user_top_artists(sp, limit=10)`
    - `get_user_top_genres(sp, limit=10)`
    - `sp.current_user_recently_played(limit=20)`
    - `get_wayback_tracks(sp, limit=10)`
    - `get_playlist_picks(sp, limit=10)`
3. Retrieves 'form_data' from the session
4. Renders `user_preferences.html` template with all gathered data

## User Reviews and Confirms Preferences:

`user_preferences.html` displays:
- Current preferences from `form_data`
- Top artists with checkboxes
- Top genres with checkboxes
- Recently played tracks with checkboxes
- Wayback tracks with checkboxes
- Playlist picks with checkboxes

User selects/deselects preferences and clicks "Confirm Preferences" button

## confirm_preferences Route:

1. Receives POST request with selected preferences
2. Stores confirmed preferences in session as 'confirmed_preferences'
3. Redirects to `/generate_playlist` route

## generate_playlist Route:

1. Retrieves Spotify client using `get_spotify_client()`
2. Retrieves 'form_data' and 'confirmed_preferences' from session
3. Calls `generate_playlist()` function

## generate_playlist Function:

### a. Process User Input:
- Extracts `activity`, `target_duration`, `energy_level`, `mood`, `genre_preferences` from `form_data` and `confirmed_preferences`

### b. Interpret Activity:
- Calls `interpret_activity_with_openai(activity, openai_client)`
- Returns `category`, `danceability`, `tempo`, `energy`, `valence`

### c. Fetch User's Spotify Data:
- Calls `get_user_top_tracks(sp, limit=50)`
- Calls `get_user_recently_played(sp, limit=50)`
- Calls `get_user_saved_tracks(sp, limit=50)`

### d. Get Recommendations:
- Calls `select_seed_tracks()` with `top_tracks`, `recent_tracks`, `saved_tracks`
- Calls `get_spotify_recommendations()` with `seed_tracks` and `genre_preferences`

### e. Combine and Deduplicate Tracks:
- Merges all fetched tracks and removes duplicates

### f. Fetch Audio Features:
- Calls `get_audio_features(sp, [track['id'] for track in all_tracks])`

### g. Enrich Track Data:
- Updates each track with its audio features
- Calls `get_track_genre(sp, track)` for each track

### h. Calculate Match Scores:
- Calls `calculate_track_match_score()` for each track
- Uses `openai_interpretation`, `energy_level`, and `mood`

### i. Select Balanced Tracks:
- Calls `select_balanced_tracks()` with `all_tracks`, `target_duration`, `openai_interpretation`, and user preferences

### j. Optimize Playlist Flow:
- Calls `optimize_playlist_flow()` with the selected tracks

### k. Return Final Playlist:
- Returns the list of track dictionaries representing the final playlist

## generate_playlist Route (continued):

1. Receives the final playlist from `generate_playlist()`
2. Stores the playlist in the session
3. Renders a template to display the generated playlist to the user

## User Reviews Generated Playlist:

- User can play previews of tracks (if available)
- User can remove tracks or request replacements
- User can adjust the order of tracks

## Save Playlist to Spotify:

1. User clicks "Save to Spotify" button
2. Calls `create_spotify_playlist()` function
    - Creates a new playlist on the user's Spotify account
    - Adds all tracks to the playlist
    - Provides user with a link to the created playlist

## Error Handling and Logging:

Throughout this process, error handling and logging should be implemented at each step. The system should gracefully handle cases where:
- Spotify API calls fail or hit rate limits
- OpenAI API calls fail
- User input is invalid or incomplete
- There are not enough tracks to meet the user's criteria