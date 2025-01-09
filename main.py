import requests
from bs4 import BeautifulSoup
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import logging
import re
import sqlite3
import os

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# SQLite database file
DATABASE_FILE = "movies.db"

# Function to initialize the SQLite database
def initialize_database():
    if not os.path.exists(DATABASE_FILE):
        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE shown_movies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT UNIQUE,
                genreList TEXT,
                release_year TEXT,
                quality TEXT,
                rating TEXT,
                story TEXT,
                link TEXT,
                added_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        conn.close()

# Function to check if a movie has been shown
def is_movie_shown(title):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT title FROM shown_movies WHERE title = ?", (title,))
    result = cursor.fetchone()
    conn.close()
    return result is not None

# Function to mark a movie as shown
def mark_movie_shown(title, genreList, release_year, quality, rating, story, link):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("""
    INSERT OR IGNORE INTO shown_movies 
    (title, genreList, release_year, quality, rating, story, link) 
    VALUES (?, ?, ?, ?, ?, ?, ?)
""", (title, genreList, release_year, quality, rating, story, link))
    conn.commit()
    conn.close()

# Function to escape Markdown special characters
def escape_markdown(text):
    escape_chars = r"\_*[]()~`>#+-=|{}.!"
    return re.sub(f"([{re.escape(escape_chars)}])", r"\\\1", text)

# Function to scrape movie details (story, release year, quality)
def scrape_movie_details(movie_url):
    try:
        response = requests.get(movie_url)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')

        # Extract story
        story = ""
        story_div = soup.find('div', class_='story')
        if story_div:
            story = story_div.find('p').text.strip()

        # Extract release year
        release_year = ""
        release_year_li = soup.find('li', string=re.compile(r'موعد الصدور :'))
        if release_year_li:
            release_year = release_year_li.find('a').text.strip()

        # Extract quality
        quality = ""
        quality_li = soup.find('li', string=re.compile(r'جودة الفيلم :'))
        if quality_li:
            quality = quality_li.find('a').text.strip()

        # Extract rating
        rating = ""
        rating_div = soup.find('div', class_='imdbS')
        if rating_div:
            rating = rating_div.find('strong').text.strip()

        # Extract IMDb link
        imdbLink = ""
        imdbLink_div = soup.find('div', class_='imdbS')
        if imdbLink_div:
            imdbLink = imdbLink_div.find('a').get('href', '')

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

# Function to scrape movies from a given URL
async def scrape_and_send_movies(chat_id: str, url: str, context: ContextTypes.DEFAULT_TYPE = None, notify_no_movies: bool = True, category: str = None):
    try:
        response = requests.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')

        # Track if any movies were sent
        movies_sent = False

        # Loop through each movie, scrape details, and send them immediately
        for item in soup.find_all('div', class_='Block--Item'):
            try:
                # Scrape basic details
                title = item.find('h3')
                if not title:
                    logger.warning("Skipping movie: Title not found")
                    continue
                title = escape_markdown(title.text.strip())  # Escape Markdown in title

                # Skip if the movie has already been shown
                if is_movie_shown(title):
                    continue

                # Extract genres
                genres = []
                genre_elements = item.find_all('li')
                if genre_elements:
                    genres = [escape_markdown(genre.text.strip()) for genre in genre_elements]

                # Extract poster URL
                poster = item.find('img')
                if poster:
                    poster = poster.get('data-src', '')
                else:
                    poster = ''

                # Extract movie link
                link = item.find('a')
                if link:
                    link = link.get('href', '')
                else:
                    logger.warning(f"Skipping movie {title}: Link not found")
                    continue

                # Scrape additional details from the movie's page
                movie_details = scrape_movie_details(link)
                titleName = escape_markdown(title)
                genreList = ', '.join(genres)
                release_year = escape_markdown(movie_details.get('release_year', 'N/A'))
                quality = escape_markdown(movie_details.get('quality', 'N/A'))
                rating = escape_markdown(movie_details.get('rating', 'N/A'))
                imdbLink = movie_details.get('imdbLink', '')
                story = escape_markdown(movie_details.get('story', 'No story available.'))

                # Prepare the caption
                caption = (
                    f"🎥 **Title:** {titleName}\n"
                    f"📚 **Genres:** {genreList}\n"
                    f"📅 **Release Year:** {release_year}\n"
                    f"🎞️ **Quality:** {quality}\n"
                )

                # Add rating only if IMDb link is available
                if imdbLink:
                    caption += f"⭐ **Rating:** [{rating}]({imdbLink})\n"
                else:
                    caption += f"⭐ **Rating:** {rating}\n"

                caption += (
                    f"📖 **Story:**\n {story}\n"
                   # f"#{category.replace(' ', '_')}"  # Add category as a hashtag
                )

                # Create a "Watch Now" button
                watch_now_button = InlineKeyboardButton("Watch Now", url=link)
                keyboard = InlineKeyboardMarkup([[watch_now_button]])

                # Send the poster as an image with the caption and button
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

                # Mark the movie as shown
                mark_movie_shown(title, genreList, release_year, quality, rating, story, link)

                # Mark that at least one movie was sent
                movies_sent = True
            except Exception as e:
                logger.warning(f"Error parsing movie item: {e}")
                continue

        # If no movies were sent and notify_no_movies is True, notify the user
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
        
# Telegram bot command: /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Define the menu options
    keyboard = [
        ["English Movies", "Hindi Movies"],
        ["Asian Movies", "Cancel"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=False, resize_keyboard=True)

    # Send the menu
    await update.message.reply_text(
        "🎬 Welcome to the Movie Bot! 🍿\n"
        "Choose a movie category:",
        reply_markup=reply_markup
    )

# Handle menu selections
async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    # Map menu options to URLs
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
    # Replace 'CHAT_ID' with the actual chat ID where you want to send updates
    chat_id = "203409328"  # Example: "-1001234567890" for a group or "123456789" for a user

    for category, url in url_map.items():
        # Call scrape_and_send_movies with the chat ID, context, and category
        await scrape_and_send_movies(chat_id, url, context, notify_no_movies=False, category=category)

    logger.info("Finished checking for new movies.")

# Main function to start the bot
def main():
    # Initialize the database
    initialize_database()

    # Replace 'YOUR_API_TOKEN' with your actual Telegram bot token
    application = Application.builder().token("7812798648:AAH8cZvRraKyRjhnxJ8UZzAnkMQKfcYbsS0").build()

    # Add command and message handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu))

    # # Schedule the periodic task to check for new movies every 5 minutes
    # job_queue = application.job_queue
    # if job_queue:
    #     job_queue.run_repeating(check_new_movies, interval=300, first=10)  # Every 5 minutes (300 seconds)
    # else:
    #     logger.error("Job queue is not available!")

    # Start the bot
    logger.info("Bot is running...")
    application.run_polling()

if __name__ == '__main__':
    main()