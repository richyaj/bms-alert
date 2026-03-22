const axios = require("axios");

const URL = "https://in.bookmyshow.com/chennai/movies/project-hail-mary/ET00451760";

const BOT_TOKEN = process.env.BOT_TOKEN;
const CHAT_ID = process.env.CHAT_ID;

async function checkBooking() {
  try {
    const response = await axios.get(URL, {
      headers: {
        "User-Agent": "Mozilla/5.0"
      }
    });

    const html = response.data.toLowerCase();

    const hasIMAX = html.includes("imax");
    const hasBooking = html.includes("book tickets") || html.includes("buy tickets");

    console.log("IMAX:", hasIMAX, "Booking:", hasBooking);

    if (hasIMAX && hasBooking) {
      await sendTelegram("🚨 IMAX Booking OPEN for Project Hail Mary in Chennai!\n\nBook now: " + URL);
    } else {
      console.log("Not open yet...");
    }

  } catch (err) {
    console.error("Error:", err.message);
  }
}

async function sendTelegram(message) {
  const telegramUrl = `https://api.telegram.org/bot${BOT_TOKEN}/sendMessage`;

  await axios.post(telegramUrl, {
    chat_id: CHAT_ID,
    text: message
  });

  console.log("Alert sent!");
}

checkBooking();