import os
import logging
import re
import requests
from bs4 import BeautifulSoup
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import psycopg2
from psycopg2 import sql

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Load environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
DATABASE_URL = os.getenv("DATABASE_URL")

if not BOT_TOKEN or not CHAT_ID or not DATABASE_URL:
    raise ValueError(
        "Please set the BOT_TOKEN, CHAT_ID, and DATABASE_URL environment variables.")

# Initialize the database
def initialize_database():
    try:
        with psycopg2.connect(DATABASE_URL) as conn:
            with conn.cursor() as cursor:
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS shown_movies (
                        id SERIAL PRIMARY KEY,
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
                logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error(f"Error initializing database: {e}")

# Check if a movie has been shown
def is_movie_shown(title):
    try:
        with psycopg2.connect(DATABASE_URL) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT title FROM shown_movies WHERE title = %s", (title,))
                result = cursor.fetchone()
                return result is not None
    except Exception as e:
        logger.error(f"Error checking if movie is shown: {e}")
        return False

# Mark a movie as shown


def mark_movie_shown(title, genreList, release_year, quality, rating, story, link, hashtag):
    try:
        with psycopg2.connect(DATABASE_URL) as conn:
            with conn.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO shown_movies 
                    (title, genreList, release_year, quality, rating, story, link, hashtag) 
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (title) DO NOTHING
                """, (title, genreList, release_year, quality, rating, story, link, hashtag))
                conn.commit()
                logger.info(f"Movie '{title}' marked as shown.")
    except Exception as e:
        logger.error(f"Error marking movie as shown: {e}")

# Escape Markdown special characters
def escape_markdown(text):
    escape_chars = r"\_*[]()~`>#+-=|{}!"
    return re.sub(f"([{re.escape(escape_chars)}])", r"\\\1", text)

# Scrape movie details
def scrape_movie_details(movie_url):
    try:
        response = requests.get(movie_url)
        response.raise_for_status()
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
    except requests.RequestException as e:
        logger.error(f"Error scraping movie details from {movie_url}: {e}")
        return {}

# Scrape and send movies
async def scrape_and_send_movies(chat_id: str, url: str, context: ContextTypes.DEFAULT_TYPE = None, notify_no_movies: bool = True, category: str = None):
    try:
        response = requests.get(url)
        response.raise_for_status()
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
                imdbLink = movie_details.get('imdbLink', '')
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
    url_map = {
        "English Movies": "https://eg1.tuktuksu.cfd/category/movies-2/%D8%A7%D9%81%D9%84%D8%A7%D9%85-%D8%A7%D8%AC%D9%86%D8%A8%D9%8A/",
        "Hindi Movies": "https://eg1.tuktuksu.cfd/category/movies-2/%d8%a7%d9%81%d9%84%d8%a7%d9%85-%d9%87%d9%86%d8%af%d9%89/",
        "Asian Movies": "https://eg1.tuktuksu.cfd/category/movies-2/%d8%a7%d9%81%d9%84%d8%a7%d9%85-%d8%a7%d8%b3%d9%8a%d9%88%d9%8a/"
    }

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
    url_map = {
        "English Movies": "https://eg1.tuktuksu.cfd/category/movies-2/%D8%A7%D9%81%D9%84%D8%A7%D9%85-%D8%A7%D8%AC%D9%86%D8%A8%D9%8A/",
        "Hindi Movies": "https://eg1.tuktuksu.cfd/category/movies-2/%d8%a7%d9%81%d9%84%d8%a7%d9%85-%d9%87%d9%86%d8%af%d9%89/",
        "Asian Movies": "https://eg1.tuktuksu.cfd/category/movies-2/%d8%a7%d9%81%d9%84%d8%a7%d9%85-%d8%a7%d8%b3%d9%8a%d9%88%d9%8a/"
    }

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