from flask import Flask, request, jsonify, session, redirect, render_template, url_for, flash
from flask_session import Session
from spotipy.oauth2 import SpotifyOAuth
from dotenv import load_dotenv
from openai import OpenAI
import os
import spotipy
import logging
from logging.handlers import RotatingFileHandler


from helpers import (
    PlaylistForm, get_user_profile, get_user_top_artists, get_user_top_genres,
    get_expanded_track_pool, parse_openai_response, find_tracks_on_spotify,
    make_spotify_request_with_retry, logger, get_openai_recommendations, PlaylistForm, 
    get_wayback_tracks, get_playlist_picks, calculate_discovery_score
)
# Load environment variables and configure app (as before)
load_dotenv()

app = Flask(__name__)
app.config['DEBUG'] = True
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_FILE_DIR'] = './.flask_session/'
Session(app)

sp_oauth = SpotifyOAuth(
    client_id=os.getenv('SPOTIFY_CLIENT_ID'),
    client_secret=os.getenv('SPOTIFY_CLIENT_SECRET'),
    redirect_uri=os.getenv('SPOTIFY_REDIRECT_URI'),
    scope='user-library-read user-read-private user-read-email playlist-modify-private user-read-recently-played user-top-read user-read-currently-playing'
)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# Set up logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Set up generate_playlist logger
generate_playlist_logger = logging.getLogger('generate_playlist')
generate_playlist_logger.setLevel(logging.DEBUG)
if not os.path.exists('logs'):
    os.makedirs('logs')
file_handler = RotatingFileHandler('logs/generate_playlist.log', maxBytes=10240, backupCount=10)
file_handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
generate_playlist_logger.addHandler(file_handler)


def get_spotify_client():
    app.logger.debug("Entering get_spotify_client function")
    token_info = session.get('token_info', None)
    
    if not token_info:
        app.logger.error("No token info found in session")
        return None

    app.logger.debug(f"Token info found: {token_info}")

    if sp_oauth.is_token_expired(token_info):
        app.logger.debug("Token is expired, attempting to refresh")
        try:
            token_info = sp_oauth.refresh_access_token(token_info['refresh_token'])
            session['token_info'] = token_info
            app.logger.debug("Token refreshed successfully")
        except Exception as e:
            app.logger.error(f"Error refreshing token: {str(e)}")
            return None

    access_token = token_info['access_token']
    app.logger.debug("Spotify client created successfully")
    return spotipy.Spotify(auth=access_token)

@app.route('/')
def index():
    app.logger.debug("Index route called")
    sp = get_spotify_client()
    if sp:
        try:
            app.logger.debug("Attempting to get user profile")
            user_profile = sp.me()
            app.logger.debug(f"User profile retrieved: {user_profile}")
        except spotipy.exceptions.SpotifyException as e:
            app.logger.error(f"SpotifyException: {str(e)}")
            user_profile = None
        app.logger.debug(f"Rendering template with user: {user_profile}")
    else:
        app.logger.debug("No Spotify client available")
        user_profile = None

    app.logger.debug(f"Template directory: {app.template_folder}")
    app.logger.debug(f"Available templates: {os.listdir(app.template_folder)}")

    try:
        return render_template('index.html', user=user_profile)
    except Exception as e:
        app.logger.error(f"Error rendering template: {str(e)}")
        return f"Error: {str(e)}", 500

@app.route('/redirect')
def redirect_page():
    code = request.args.get('code')
    token_info = sp_oauth.get_access_token(code)
    session['token_info'] = token_info
    return redirect(url_for('initial_form'))

@app.route('/login')
def login():
    app.logger.debug("Login route called")
    auth_url = sp_oauth.get_authorize_url()
    app.logger.debug(f"Generated auth URL: {auth_url}")
    return redirect(auth_url)

@app.route('/initial_form', methods=['GET', 'POST'])
def initial_form():
    app.logger.info("Entering initial_form function")
    
    form = PlaylistForm()
    
    if request.method == 'POST':
        app.logger.debug("POST request received in initial_form")
        app.logger.debug(f"Form data: {request.form}")
        if form.validate_on_submit():
            app.logger.debug("Form submitted and validated")
            try:
                # Convert duration from minutes to number of tracks
                duration_minutes = form.duration.data
                num_tracks = round(duration_minutes / 3.5)
                
                # Process form data
                form_data = {
                    'name': form.name.data,
                    'mood': form.mood.data,
                    'desired_mood': form.desired_mood.data,
                    'activity': form.activity.data,
                    'energy_level': form.energy_level.data,
                    'time_of_day': form.time_of_day.data,
                    'duration_minutes': duration_minutes,
                    'num_tracks': num_tracks,
                    'discovery_level': form.discovery_level.data,
                    'favorite_artists': form.favorite_artists.data,
                    'favorite_genres': form.favorite_genres.data,
                    'playlist_description': form.playlist_description.data
                }
                session['form_data'] = form_data
                app.logger.debug(f"Form data saved to session: {form_data}")
                
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    app.logger.debug("AJAX request detected, returning JSON response")
                    return jsonify({"success": True, "message": "Form data received successfully"})
                else:
                    app.logger.info("Redirecting to load_user_preferences")
                    return redirect(url_for('load_user_preferences'))
            except Exception as e:
                app.logger.error(f"Error processing form data: {str(e)}", exc_info=True)
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({"success": False, "message": "An error occurred while processing your form."}), 500
                else:
                    flash('An error occurred while processing your form. Please try again.', 'danger')
        else:
            app.logger.warning(f"Form validation failed. Errors: {form.errors}")
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({"success": False, "message": "Form validation failed", "errors": form.errors}), 400
            else:
                flash('Please correct the errors in the form and try again.', 'danger')
    
    app.logger.debug("Rendering initial form template")
    return render_template('initial_form.html', form=form)

@app.route('/save_playlist', methods=['POST'])
def save_playlist():
    sp = get_spotify_client()
    if not sp:
        flash('Unable to authenticate with Spotify', 'danger')
        return redirect(url_for('index'))

    recommended_tracks = session.get('recommended_tracks')
    ai_playlist_description = session.get('ai_playlist_description')
    form_data = session.get('form_data')

    if not all([recommended_tracks, ai_playlist_description, form_data]):
        flash('Missing required data. Please start over.', 'danger')
        return redirect(url_for('initial_form'))

    try:
        selected_tracks = find_tracks_on_spotify(sp, recommended_tracks)

        user_id = sp.current_user()['id']
        playlist_name = f"MoodWave: {form_data.get('activity', 'Custom').capitalize()} - {form_data.get('energy_level', 'Medium')} Energy"
        
        playlist = make_spotify_request_with_retry(
            sp, 'user_playlist_create', user_id, name=playlist_name, public=False, description=ai_playlist_description[:300])

        if selected_tracks:
            for i in range(0, len(selected_tracks), 100):
                chunk = selected_tracks[i:i+100]
                make_spotify_request_with_retry(
                    sp, 'user_playlist_add_tracks', user_id, playlist['id'], chunk)

        flash('Playlist saved successfully!', 'success')
        return render_template('playlist_saved.html', playlist=playlist, num_tracks=len(selected_tracks))

    except Exception as e:
        logger.error(f"Error saving playlist: {e}")
        flash(f'Error saving playlist: {str(e)}', 'danger')
        return redirect(url_for('generate_playlist'))

@app.route('/sign_out')
def sign_out():
    app.logger.debug("Sign out route called")
    session.clear()
    app.logger.info("Session cleared")
    return redirect(url_for('index'))

@app.route('/load_user_preferences', methods=['GET'])
def load_user_preferences():
    app.logger.debug("Entering load_user_preferences function")
    
    try:
        sp = get_spotify_client()
        if not sp:
            app.logger.error("Unable to get Spotify client, redirecting to initial_form")
            flash('Unable to authenticate with Spotify. Please try logging in again.', 'danger')
            return redirect(url_for('initial_form'))

        # Retrieve form data from session
        form_data = session.get('form_data', {})
        app.logger.debug(f"Retrieved form data from session: {form_data}")

        # Get user profile
        user_profile = get_user_profile(sp)
        app.logger.debug(f"User profile retrieved: {user_profile}")

        # Get top artists and genres
        top_artists = get_user_top_artists(sp, limit=10)
        top_genres = get_user_top_genres(sp, limit=10)
        app.logger.debug(f"Top artists: {top_artists}")
        app.logger.debug(f"Top genres: {top_genres}")

        # Get recently played tracks
        recent_tracks = sp.current_user_recently_played(limit=20)['items']
        app.logger.debug(f"Recent tracks retrieved: {len(recent_tracks)}")

        # Get "Way Back Machine" tracks
        wayback_tracks = get_wayback_tracks(sp, limit=10)
        app.logger.debug(f"Wayback tracks retrieved: {len(wayback_tracks)}")

        # Get Playlist Picks
        playlist_picks = get_playlist_picks(sp, limit=10)
        app.logger.debug(f"Playlist picks retrieved: {len(playlist_picks)}")

        return render_template('user_preferences.html',
                               user_profile=user_profile,
                               top_artists=top_artists,
                               top_genres=top_genres,
                               recent_tracks=recent_tracks,
                               wayback_tracks=wayback_tracks,
                               playlist_picks=playlist_picks,
                               form_data=form_data)
    except Exception as e:
        app.logger.error(f"Error in load_user_preferences: {str(e)}", exc_info=True)
        flash('An error occurred while loading your preferences. Please try again.', 'danger')
        return redirect(url_for('initial_form'))

@app.route('/find_tracks', methods=['GET'])
def find_tracks():
    sp = get_spotify_client()
    if not sp:
        flash('Unable to authenticate with Spotify', 'danger')
        return redirect(url_for('index'))

    form_data = session.get('form_data')
    user_profile = session.get('user_profile')
    favorite_artists = session.get('favorite_artists')
    favorite_genres = session.get('favorite_genres')

    if not all([form_data, user_profile, favorite_artists, favorite_genres]):
        flash('Missing required data. Please start over.', 'danger')
        return redirect(url_for('initial_form'))

    try:
        familiar_tracks, discovery_tracks = get_expanded_track_pool(sp, favorite_artists, favorite_genres, user_profile)
        all_tracks = familiar_tracks + discovery_tracks

        # Limit to 200 tracks
        all_tracks = all_tracks[:200]

        session['all_tracks'] = all_tracks

        return render_template('tracks_found.html', 
                               num_tracks=len(all_tracks),
                               sample_tracks=all_tracks[:10])  # Show first 10 tracks as a sample
    except Exception as e:
        logger.error(f"Error finding tracks: {e}")
        flash(f'Error finding tracks: {str(e)}', 'danger')
        return redirect(url_for('review_preferences'))
    
@app.route('/autocomplete_artist')
def autocomplete_artist():
    query = request.args.get('q', '')
    sp = get_spotify_client()
    if not sp:
        return jsonify([])

    try:
        results = sp.search(q=query, type='artist', limit=5)
        artists = results['artists']['items']
        return jsonify([{'value': artist['name'], 'name': artist['name']} for artist in artists])
    except Exception as e:
        logger.error(f"Error in artist autocomplete: {e}")
        return jsonify([])

@app.route('/autocomplete_genre')
def autocomplete_genre():
    query = request.args.get('q', '')
    sp = get_spotify_client()
    if not sp:
        return jsonify([])

    try:
        genres = sp.recommendation_genre_seeds()
        matched_genres = [genre for genre in genres if query.lower() in genre.lower()]
        return jsonify([{'value': genre, 'name': genre} for genre in matched_genres[:5]])
    except Exception as e:
        logger.error(f"Error in genre autocomplete: {e}")
        return jsonify([])

@app.route('/generate_playlist', methods=['GET'])
def generate_playlist():
    logger.info("Entering generate_playlist function")
    try:
        sp = get_spotify_client()
        if not sp:
            logger.error("Failed to get Spotify client")
            flash('Unable to authenticate with Spotify', 'danger')
            return redirect(url_for('index'))

        initial_form_data = session.get('form_data', {})
        confirmed_preferences = session.get('confirmed_preferences', {})

        logger.debug(f"Initial form data: {initial_form_data}")
        logger.debug(f"Confirmed preferences: {confirmed_preferences}")

        def safe_float(value, default=50.0):
            try:
                return float(value) if value != '' else default
            except (ValueError, TypeError):
                logger.warning(f"Could not convert {value} to float, using default {default}")
                return default

        user_preferences = {
            "current_mood": safe_float(initial_form_data.get('mood')),
            "desired_mood": safe_float(initial_form_data.get('desired_mood')),
            "activity": initial_form_data.get('activity', ''),
            "energy_level": safe_float(initial_form_data.get('energy_level')),
            "time_of_day": initial_form_data.get('time_of_day', ''),
            "discovery_level": safe_float(initial_form_data.get('discovery_level', 30)) / 100,
            "playlist_description": initial_form_data.get('playlist_description', ''),
            "selected_artists": confirmed_preferences.get('artists', []),
            "selected_genres": confirmed_preferences.get('genres', []),
            "selected_tracks": (
                confirmed_preferences.get('recentTracks', []) +
                confirmed_preferences.get('waybackTracks', []) +
                confirmed_preferences.get('playlistPicks', [])
            )
        }

        logger.debug(f"Processed user preferences: {user_preferences}")

        # Generate expanded track pool
        familiar_tracks, discovery_tracks = get_expanded_track_pool(
            sp, 
            user_preferences['selected_artists'], 
            user_preferences['selected_genres'], 
            sp.me(),
            discovery_ratio=user_preferences['discovery_level']
        )
        
        logger.debug(f"Generated track pool - Familiar tracks: {len(familiar_tracks)}, Discovery tracks: {len(discovery_tracks)}")

        # Combine all tracks and remove duplicates
        all_tracks = familiar_tracks + discovery_tracks
        all_tracks = list({track['id']: track for track in all_tracks}.values())

        # Limit to 200 tracks, maintaining the discovery ratio
        discovery_count = int(200 * user_preferences['discovery_level'])
        familiar_count = 200 - discovery_count
        all_tracks = (
            sorted(familiar_tracks, key=lambda x: x.get('discovery_score', 0))[:familiar_count] +
            sorted(discovery_tracks, key=lambda x: x.get('discovery_score', 0), reverse=True)[:discovery_count]
        )

        logger.debug(f"Final track pool size: {len(all_tracks)}")

        # Call OpenAI for recommendations
        try:
            openai_response = get_openai_recommendations(
                client, 
                user_preferences, 
                all_tracks, 
                num_tracks=int(safe_float(initial_form_data.get('duration', 30)))
            )
            logger.debug(f"Raw OpenAI response: {openai_response}")
            
        except Exception as e:
            logger.error(f"Error getting OpenAI recommendations: {str(e)}", exc_info=True)
            flash('Error generating playlist recommendations. Please try again.', 'danger')
            return redirect(url_for('load_user_preferences'))

        # Parse OpenAI response
        recommended_tracks, ai_playlist_description, explanation = parse_openai_response(openai_response)

        # Find tracks on Spotify
        spotify_track_ids = find_tracks_on_spotify(sp, recommended_tracks)

        # Store results in session
        session['recommended_tracks'] = recommended_tracks
        session['ai_playlist_description'] = ai_playlist_description
        session['explanation'] = explanation
        session['spotify_track_ids'] = spotify_track_ids

        logger.info("Successfully generated playlist. Rendering preview.")
        return render_template('playlist_preview.html',
                               recommended_tracks=recommended_tracks,
                               ai_playlist_description=ai_playlist_description,
                               explanation=explanation)

    except Exception as e:
        logger.error(f"Unexpected error in generate_playlist: {str(e)}", exc_info=True)
        flash('An unexpected error occurred. Please try again.', 'danger')
        return redirect(url_for('load_user_preferences'))

        # Parse OpenAI response
        recommended_tracks, ai_playlist_description, explanation = parse_openai_response(openai_response)

        # Find tracks on Spotify
        spotify_track_ids = find_tracks_on_spotify(sp, recommended_tracks)

        # Store results in session
        session['recommended_tracks'] = recommended_tracks
        session['ai_playlist_description'] = ai_playlist_description
        session['explanation'] = explanation
        session['spotify_track_ids'] = spotify_track_ids

        logger.info("Successfully generated playlist. Rendering preview.")
        return render_template('playlist_preview.html',
                               recommended_tracks=recommended_tracks,
                               ai_playlist_description=ai_playlist_description,
                               explanation=explanation)

    except Exception as e:
        logger.error(f"Unexpected error in generate_playlist: {str(e)}", exc_info=True)
        flash('An unexpected error occurred. Please try again.', 'danger')
        return redirect(url_for('load_user_preferences'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8888, debug=True)
    
@app.route('/confirm_preferences', methods=['POST'])
def confirm_preferences():
    logger.debug("Entering confirm_preferences route")
    try:
        preferences = request.form.to_dict()
        logger.debug(f"Received preferences: {preferences}")
        session['form_data'] = preferences
        logger.info("Preferences confirmed and stored in session")
        return jsonify({"success": True, "message": "Preferences confirmed successfully"})
    except Exception as e:
        logger.error(f"Error in confirm_preferences: {str(e)}")
        return jsonify({"success": False, "message": str(e)}), 400
    finally:
        logger.debug("Exiting confirm_preferences route")