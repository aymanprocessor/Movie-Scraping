import os
import logging
import re
import sqlite3
import json
import requests
from bs4 import BeautifulSoup
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv  # Import the dotenv module

# Load environment variables from .env file
load_dotenv()

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Load environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

if not BOT_TOKEN or not CHAT_ID:
    raise ValueError(
        "Please set the BOT_TOKEN and CHAT_ID environment variables in the .env file."
    )

# SQLite database file
DATABASE_FILE = "movies.db"

# Load URLs from the JSON file


def load_urls():
    with open('urls.json', 'r') as file:
        return json.load(file)

# Initialize the database
def initialize_database():
    if not os.path.exists(DATABASE_FILE):
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS shown_movies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT UNIQUE,
                genreList TEXT,
                release_year TEXT,
                quality TEXT,
                rating TEXT,
                story TEXT,
                link TEXT,
                hashtag TEXT,
                added_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        conn.close()
        logger.info("Database initialized successfully.")

# Check if a movie has been shown
def is_movie_shown(title):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT title FROM shown_movies WHERE title = ?", (title,))
    result = cursor.fetchone()
    conn.close()
    return result is not None

# Mark a movie as shown
def mark_movie_shown(title, genreList, release_year, quality, rating, story, link, hashtag):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR IGNORE INTO shown_movies 
        (title, genreList, release_year, quality, rating, story, link, hashtag) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (title, genreList, release_year, quality, rating, story, link, hashtag))
    conn.commit()
    conn.close()
    logger.info(f"Movie '{title}' marked as shown.")

# Escape Markdown special characters
def escape_markdown(text):
    escape_chars = r"\_*[]()~`>#+-=|{}!"
    return re.sub(f"([{re.escape(escape_chars)}])", r"\\\1", text)

# Scrape movie details
def scrape_movie_details(movie_url):
    try:
        response = requests.get(movie_url, allow_redirects=True)
        response.raise_for_status()

        # Check if the response status code is 200 OK
        if response.status_code != 200:
            logger.error(
                f"Received non-200 status code: {response.status_code}")
            return {}

        soup = BeautifulSoup(response.content, 'html.parser')

        story = soup.find('div', class_='story').find(
            'p').text.strip() if soup.find('div', class_='story') else ""
        release_year = soup.find('li', string=re.compile(r'موعد الصدور :')).find(
            'a').text.strip() if soup.find('li', string=re.compile(r'موعد الصدور :')) else ""
        quality = soup.find('li', string=re.compile(r'جودة الفيلم :')).find(
            'a').text.strip() if soup.find('li', string=re.compile(r'جودة الفيلم :')) else ""
        rating = soup.find('div', class_='imdbS').find(
            'strong').text.strip() if soup.find('div', class_='imdbS') else ""
        imdbLink = soup.find('div', class_='imdbS').find('a').get(
            'href', '') if soup.find('div', class_='imdbS') else ""

        return {
            'story': story,
            'release_year': release_year,
            'quality': quality,
            'rating': rating,
            'imdbLink': imdbLink
        }
    except requests.exceptions.TooManyRedirects:
        logger.error(f"Too many redirects for URL: {movie_url}")
        return {}
    except requests.RequestException as e:
        logger.error(f"Error scraping movie details from {movie_url}: {e}")
        return {}

# Scrape and send movies
async def scrape_and_send_movies(chat_id: str, url: str, context: ContextTypes.DEFAULT_TYPE = None, notify_no_movies: bool = True, category: str = None):
    try:
        response = requests.get(url, allow_redirects=True)
        response.raise_for_status()

        # Check if the response status code is 200 OK
        if response.status_code != 200:
            logger.error(
                f"Received non-200 status code: {response.status_code}")
            await context.bot.send_message(
                chat_id=chat_id,
                text="An error occurred while fetching movies. Please try again later.",
                reply_markup=ReplyKeyboardRemove()
            )
            return

        soup = BeautifulSoup(response.content, 'html.parser')

        movies_sent = False
        for item in soup.find_all('div', class_='Block--Item'):
            try:
                title = item.find('h3')
                if not title:
                    continue
                title = escape_markdown(title.text.strip())

                if is_movie_shown(title):
                    continue

                genres = [escape_markdown(genre.text.strip())
                          for genre in item.find_all('li')]
                poster = item.find('img').get(
                    'data-src', '') if item.find('img') else ''
                link = item.find('a').get('href', '') if item.find('a') else ''

                if not link:
                    continue

                movie_details = scrape_movie_details(link)
                titleName = escape_markdown(title)
                genreList = ', '.join(genres)
                release_year = escape_markdown(movie_details.get('release_year', 'N/A'))
                quality = escape_markdown(movie_details.get('quality', 'N/A'))
                rating = escape_markdown(movie_details.get('rating', 'N/A'))
                imdbLink = movie_details.get('imdbLink', 'N/A')
                story = escape_markdown(movie_details.get('story', 'No story available.'))

                # Add the category as a hashtag
                hashtag = f"#{category.replace(' ', '')}" if category else ""

                caption = (
                    f"🎥 **Title:** {titleName}\n"
                    f"📚 **Genres:** {genreList}\n"
                    f"📅 **Release Year:** {release_year}\n"
                    f"🎞️ **Quality:** {quality}\n"
                )

                if imdbLink:
                    caption += f"⭐ **Rating:** [{rating}]({imdbLink})\n"
                else:
                    caption += f"⭐ **Rating:** {rating}\n"

                caption += f"📖 **Story:**\n {story}\n"
                caption += f"{hashtag}\n"  # Add the hashtag at the end

                watch_now_button = InlineKeyboardButton("Watch Now", url=link)
                keyboard = InlineKeyboardMarkup([[watch_now_button]])

                if poster:
                    await context.bot.send_photo(
                        chat_id=chat_id,
                        photo=poster,
                        caption=caption,
                        parse_mode="Markdown",
                        reply_markup=keyboard
                    )
                else:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=caption,
                        parse_mode="Markdown",
                        reply_markup=keyboard
                    )

                # Pass the hashtag to mark_movie_shown
                mark_movie_shown(title, genreList, release_year,
                                 quality, rating, story, link, hashtag)
                movies_sent = True
            except Exception as e:
                logger.warning(f"Error parsing movie item: {e}")
                continue

        if not movies_sent and notify_no_movies:
            await context.bot.send_message(
                chat_id=chat_id,
                text="No new movies found in this category.",
                reply_markup=ReplyKeyboardRemove()
            )
    except requests.exceptions.TooManyRedirects:
        logger.error(f"Too many redirects for URL: {url}")
        await context.bot.send_message(
            chat_id=chat_id,
            text="Too many redirects encountered. Please try again later.",
            reply_markup=ReplyKeyboardRemove()
        )
    except requests.RequestException as e:
        logger.error(f"Error scraping movies: {e}")
        await context.bot.send_message(
            chat_id=chat_id,
            text="An error occurred while fetching movies. Please try again later.",
            reply_markup=ReplyKeyboardRemove()
        )

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        ["English Movies", "Hindi Movies"],
        ["Asian Movies", "Cancel"]
    ]
    reply_markup = ReplyKeyboardMarkup(
        keyboard, one_time_keyboard=False, resize_keyboard=True)
    await update.message.reply_text(
        "🎬 Welcome to the Movie Bot! 🍿\n"
        "Choose a movie category:",
        reply_markup=reply_markup
    )

# Handle menu selections
async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    url_map = load_urls()  # Load URLs from the JSON file

    if text in url_map:
        await update.message.reply_text(f"Fetching {text}...", reply_markup=ReplyKeyboardRemove())
        await scrape_and_send_movies(update.effective_chat.id, url_map[text], context, category=text)
    elif text == "Cancel":
        await update.message.reply_text("Menu canceled.", reply_markup=ReplyKeyboardRemove())
    else:
        await update.message.reply_text("Invalid option. Please try again.", reply_markup=ReplyKeyboardRemove())

# Periodic task to check for new movies
async def check_new_movies(context: ContextTypes.DEFAULT_TYPE):
    logger.info("Checking for new movies...")
    url_map = load_urls()  # Load URLs from the JSON file

    for category, url in url_map.items():
        try:
            await scrape_and_send_movies(CHAT_ID, url, context, notify_no_movies=False, category=category)
        except Exception as e:
            logger.error(f"Error checking new movies for {category}: {e}")

    logger.info("Finished checking for new movies.")

# Help command
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "🎬 **Movie Bot Help** 🍿\n\n"
        "Use the following commands:\n"
        "/start - Start the bot and show the menu.\n"
        "/help - Show this help message.\n\n"
        "Choose a category from the menu to get movie recommendations."
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

# Main function
def main():
    initialize_database()
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu))

    if application.job_queue:
        application.job_queue.run_repeating(
            check_new_movies, interval=300, first=10)
    else:
        logger.error("Job queue is not available!")

    logger.info("Bot is running...")
    application.run_polling()

if __name__ == '__main__':
    main()