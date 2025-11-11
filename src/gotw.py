import asyncio
from datetime import datetime, timedelta
import json
import os
import pytz
import sqlite3
import time

from logs import log_info, log_warning, log_error

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'dat', 'gotw.db')

# Load config.json
CONFIG_PATH = os.path.join(os.path.dirname(__file__), '..', 'config.json')
log_info(f'Loading config from {CONFIG_PATH}')
try:
    with open(CONFIG_PATH, 'r') as f:
        config = json.load(f)
    # Get schedule settings from config, with defaults
    schedule = config.get('schedule', {})
    update_time = schedule.get('time', '00:00')
    timezone_str = schedule.get('timezone', 'utc')
    update_day = schedule.get('updateDay', 'Monday')  # Always use Monday by default for ISO week consistency
    # Frequency can be 'weekly' (default) or 'daily'
    frequency = schedule.get('frequency', 'weekly')
    start_week = schedule.get('startWeek', 1)  # Week 1-52
    end_week = schedule.get('endWeek', 52)  # Week 1-52
    
    # Get update behavior settings
    update_settings = config.get('updateSettings', {})
    retry_attempts = update_settings.get('retryAttempts', 3)
    retry_delay = update_settings.get('retryDelayMinutes', 60)
    allow_backdate = update_settings.get('allowBackdate', True)
    
    log_info(f'Loaded config: time = {update_time}, timezone = {timezone_str}, '
             f'update day = {update_day}, weeks = {start_week}-{end_week}, frequency = {frequency}')
except Exception as e:
    log_error(f'Error loading config file: {e}')
    raise
tz = pytz.timezone(timezone_str)

# Get the current date in the configured timezone
global current_date
current_date = datetime.now(tz).strftime('%d-%m-%Y')
log_info(f'Current date in {timezone_str} timezone: {current_date}')

# Initialize the Grammar of the Week variables
date = word = ipa = pos = definition = ''

def init_db():
    try:
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS words (
                date TEXT PRIMARY KEY,  -- DD-MM-YYYY format
                word TEXT NOT NULL,
                ipa TEXT,
                pos TEXT,
                definition TEXT,
                UNIQUE(date)
            )''')
        log_info('Database initialized successfully.')
    except Exception as e:
        log_error(f'Failed to initialize database: {e}')

def set_gotw(new_date, new_word, new_ipa, new_pos, new_definition):
    global date, word, ipa, pos, definition
    date = new_date
    word = new_word
    ipa = new_ipa
    pos = new_pos
    definition = new_definition
    log_info(f'Set Grammar of the Week: {date}, {word}, {ipa}, {pos}, {definition}')

def query_word(date):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute('''SELECT word, ipa, pos, definition FROM words WHERE date = ?''', (date,))
        result = c.fetchone()
        if result:
            return {
                'date': date,
                'word': result[0],
                'ipa': result[1],
                'pos': result[2],
                'definition': result[3]
            }
        else:
            return None

def query_previous(date, limit=1):
    if not date:
        raise ValueError('Date cannot be empty.')
    if limit > 8:
        raise ValueError('Limit cannot exceed 8.')
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        # Ensure dates are compared correctly by converting them to a consistent format
        c.execute('''SELECT date, word, ipa, pos, definition FROM words 
                     WHERE strftime('%Y-%m-%d', substr(date, 7, 4) || '-' || substr(date, 4, 2) || '-' || substr(date, 1, 2)) < 
                           strftime('%Y-%m-%d', substr(?, 7, 4) || '-' || substr(?, 4, 2) || '-' || substr(?, 1, 2)) 
                     ORDER BY strftime('%Y-%m-%d', substr(date, 7, 4) || '-' || substr(date, 4, 2) || '-' || substr(date, 1, 2)) DESC 
                     LIMIT ?''', (date, date, date, limit))
        results = c.fetchall()
        # Check if there are no more entries before the earliest date in the results
        if results:
            c.execute('''SELECT COUNT(*) FROM words 
                         WHERE strftime('%Y-%m-%d', substr(date, 7, 4) || '-' || substr(date, 4, 2) || '-' || substr(date, 1, 2)) < 
                               strftime('%Y-%m-%d', substr(?, 7, 4) || '-' || substr(?, 4, 2) || '-' || substr(?, 1, 2))''', 
                      (results[-1][0], results[-1][0], results[-1][0]))
            has_more = c.fetchone()[0] > 0
        else:
            has_more = False
        return {
            'results': [{'date': row[0], 'word': row[1], 'ipa': row[2], 'pos': row[3], 'definition': row[4]} for row in results],
            'has_more': has_more
        }

def find_gotw(word):
    if not word:
        raise ValueError('Word cannot be empty.')
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute('''SELECT date, word, ipa, pos, definition FROM words WHERE word = ?''', (word,))
        result = c.fetchall()
        if result:
            return [{'date': row[0], 'word': row[1], 'ipa': row[2], 'pos': row[3], 'definition': row[4]} for row in result]
        else:
            return None

def append_word(date, word, ipa, pos, definition):
    if date is None:  # If date is None, use the date after the most recent one used in the database
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute('''SELECT date FROM words 
                      ORDER BY strftime('%Y-%m-%d', substr(date, 7, 4) || '-' || substr(date, 4, 2) || '-' || substr(date, 1, 2)) DESC 
                      LIMIT 1''')
            last_date = c.fetchone()
            if last_date:
                # Get the next date depending on configured frequency
                last_dt = datetime.strptime(last_date[0], '%d-%m-%Y')
                if frequency.lower() == 'daily':
                    next_dt = last_dt + timedelta(days=1)
                else:
                    # Default weekly behavior: next Monday
                    days_until_monday = (7 - last_dt.weekday()) or 7  # If already Monday, go to next Monday
                    next_dt = last_dt + timedelta(days=days_until_monday)
                date = next_dt.strftime('%d-%m-%Y')
            else:
                date = datetime.now(tz).strftime('%d-%m-%Y')

    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute('''INSERT OR REPLACE INTO words (date, word, ipa, pos, definition)
                     VALUES (?, ?, ?, ?, ?)''', (date, word, ipa, pos, definition))
        conn.commit()

    return date


def compute_next_update(now=None):
    """Compute the next scheduled update datetime based on current config.
    Returns (next_update: datetime, next_week: int|None).
    For daily frequency, next_week will be None.
    """
    if now is None:
        now = datetime.now(tz)
    hour, minute = map(int, update_time.split(':'))

    if frequency.lower() == 'daily':
        next_update = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if next_update <= now:
            next_update = next_update + timedelta(days=1)
        return next_update, None

    # Weekly scheduling (existing behavior)
    current_year = now.year
    current_week = int(now.strftime('%V'))  # ISO week number (1-53)

    # Convert update day name to weekday number (0=Monday ... 6=Sunday)
    update_weekday = time.strptime(update_day, '%A').tm_wday

    # Find next valid week number
    if current_week < start_week:
        next_week = start_week
    elif current_week > end_week:
        next_week = start_week
        current_year += 1
    elif current_week >= start_week and current_week < end_week:
        next_week = current_week + 1
    else:  # current_week == end_week
        next_week = start_week
        current_year += 1

    # Calculate the date of Monday in the target week
    jan_1 = datetime(current_year, 1, 1, tzinfo=tz)
    week_1_monday = jan_1 + timedelta(days=(-jan_1.weekday()))
    if jan_1.weekday() > 3:  # ISO week 1 starts on previous year if Jan 1 is after Thursday
        week_1_monday += timedelta(weeks=1)
    target_monday = week_1_monday + timedelta(weeks=next_week-1)

    # Add days to get to our target update day
    target_date = target_monday + timedelta(days=update_weekday)

    next_update = target_date.replace(hour=hour, minute=minute, second=0, microsecond=0)

    # If we've passed the time today, move to next week if needed
    if next_update <= now:
        if next_week < end_week:
            next_week += 1
            target_monday = week_1_monday + timedelta(weeks=next_week-1)
            target_date = target_monday + timedelta(days=update_weekday)
            next_update = target_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
        else:
            # Move to first week of next year
            current_year += 1
            next_week = start_week
            jan_1 = datetime(current_year, 1, 1, tzinfo=tz)
            week_1_monday = jan_1 + timedelta(days=(-jan_1.weekday()))
            if jan_1.weekday() > 3:
                week_1_monday += timedelta(weeks=1)
            target_monday = week_1_monday + timedelta(weeks=next_week-1)
            target_date = target_monday + timedelta(days=update_weekday)
            next_update = target_date.replace(hour=hour, minute=minute, second=0, microsecond=0)

    return next_update, next_week

async def gotw_main_loop():
    global current_date, date, word, ipa, pos, definition

    # Initialize the database if it doesn't exist
    if not os.path.exists(DB_PATH) or os.path.getsize(DB_PATH) == 0:
        log_info('GOTW database is not initialized. Initializing...')
        try:
            init_db()
        except Exception as e:
            log_error(f'Failed to initialize database: {e}')

    # Load the GOTW entry for the current week to display immediately
    current_week = int(datetime.now(tz).strftime('%V'))  # ISO week number
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        # Try to find an entry for any date in the current week
        # Get Monday of current week to search
        now = datetime.now(tz)
        monday_this_week = now - timedelta(days=now.weekday())
        monday_str = monday_this_week.strftime('%d-%m-%Y')
        
        c.execute('''SELECT date, word, ipa, pos, definition FROM words WHERE date = ?''', (monday_str,))
        entry = c.fetchone()
        
        if entry:
            current_date = entry[0]
            date = entry[0]
            word = entry[1]
            ipa = entry[2]
            pos = entry[3]
            definition = entry[4]
            log_info(f'Loaded GOTW for current week: {date} - {word}')
        else:
            # If no entry for this week's Monday, load the latest entry
            c.execute('''SELECT date, word, ipa, pos, definition FROM words 
                         ORDER BY strftime('%Y-%m-%d', substr(date, 7, 4) || '-' || substr(date, 4, 2) || '-' || substr(date, 1, 2)) DESC 
                         LIMIT 1''')
            latest = c.fetchone()
            if latest:
                current_date = latest[0]
                date = latest[0]
                word = latest[1]
                ipa = latest[2]
                pos = latest[3]
                definition = latest[4]
                log_info(f'No entry for current week. Loaded latest GOTW: {date} - {word}')
            else:
                log_warning('No GOTW entries found in database')

    # Loop to get the Grammar of the Week on the scheduled frequency
    log_info('Starting Grammar of the Week loop...')
    while True:
        # Calculate time until next update using helper function
        now = datetime.now(tz)
        next_update, next_week = compute_next_update(now)
        
        if frequency.lower() == 'daily':
            log_info(f'Next update scheduled (daily) for {next_update.strftime("%Y-%m-%d %H:%M %Z")}')
        else:
            log_info(f'Next update scheduled for Week {next_week} ({next_update.strftime("%Y-%m-%d %H:%M %Z")})')
        time_until_next = next_update - now
        
        if frequency.lower() == 'daily':
            log_info(f'Waiting for {time_until_next.total_seconds()} seconds until next daily Grammar update...')
        else:
            log_info(f'Waiting for {time_until_next.total_seconds()} seconds until next weekly Grammar of the Week...')
        await asyncio.sleep(time_until_next.total_seconds())  # Sleep until next update
        current_date = next_update.strftime('%d-%m-%Y')
        log_info(f'Current date updated to {current_date}')
