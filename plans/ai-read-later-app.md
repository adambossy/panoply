# 🧠 Read Later App — Project Plan

## **Overview**

A “Read Later” app for collecting, summarizing, and revisiting online articles — enhanced by AI-powered extraction, summarization, contextualization, and memory tracking. The end goal is to create a personalized reading companion that helps you not only save and read articles, but also remember and engage with them over time.

---

## **Phase 1 — Core Data Model and Input Form**

### **Goals**

Establish the backend foundation and a simple input flow for saving articles manually.

### **Tasks**

* **Design the database schema** for saved articles. Each record should include:

  * `id`
  * `title`
  * `url`
  * `extracted_text`
  * `ai_summary`
  * `created_at`
  * `updated_at`
  * `is_read`
  * `tags` or `topics`
  * any other relevant metadata (e.g. `source_domain`, `reading_time`)
* **Build a minimal web form** for adding articles manually.

  * Form fields: title, URL, and optional notes.
  * Store new entries in the database.
  * Provide a lightweight backend (e.g., FastAPI or Supabase) for quick writes.

---

## **Phase 2 — Browser Bookmarklet**

### **Goals**

Enable one-click saving of any webpage directly from the browser.

### **Tasks**

* Create a **bookmarklet** (or browser extension later) that:

  * Sends the current page’s URL and title to the backend API.
  * Automatically checks whether the URL already exists in the database.

    * If not saved → display a “Saved” confirmation.
    * If already saved → toggle to “Remove” to delete it.
* Focus on instant UX feedback — minimal UI, small overlay, quick API roundtrip.

---

## **Phase 2.1 — Mobile Bookmark Shortcut**

### **Goals**

Provide mobile Safari compatibility for saving articles on iOS.

### **Tasks**

* Create a **mobile bookmark shortcut or share extension**.

  * When activated from Safari’s share sheet, it posts the current URL to the same API endpoint used by the web form/bookmarklet.

---

## **Phase 2.5 — Text Extraction Pipeline**

### **Goals**

Extract article text cleanly and efficiently for offline reading and AI analysis.

### **Tasks**

* Implement **content extraction** using one of:

  * A lightweight AI model (e.g. GPT-4-mini) for structure + noise filtering.
  * OR existing APIs (like Mercury Parser, Diffbot, or Newspaper3k) if available for free or low-cost.
* Store the clean text body in `extracted_text` for each article.

---

## **Phase 3 — AI Summarization and Contextual Insights**

### **Goals**

Use AI to generate meaningful, structured summaries for each saved article.

### **Summary Output Structure**

For each article, generate:

1. **Abstract-style summary** — one generous paragraph.
2. **Top 3–5 key insights**, each 1–2 sentences long.
3. **Supporting verbatim passages** — direct quotes that best illustrate those insights.
4. **Contextual bullets** (conditional):

   * For **academic papers**: 3–5 points summarizing the methodology.
   * For **news articles**: 3–5 bullets situating the story in its broader global or political context.

### **Implementation**

* Trigger summarization at article creation or on-demand.
* Use GPT-4-mini or similar for efficiency; fall back to local cache to avoid reprocessing the same URLs.

---

## **Phase 4 — Reading Interface (Web UI)**

### **Goals**

Provide a simple, mobile-friendly page for browsing and reading saved content.

### **Features**

* Display articles sorted **reverse-chronologically**.
* Each article shows:

  * Title and source.
  * AI summary.
  * Extracted text (expand/collapse).
* Clean typography, distraction-free reading experience (no ads, no clutter).

---

## **Phase 4.1 — Read Tracking and Memory Module**

### **Goals**

Track what you’ve read and gradually build a “memory” of your knowledge base.

### **Tasks**

* Define a **read unit** (“element”) as:

  * A section of the summary (abstract, key insight, or supporting passage), OR
  * A paragraph in the extracted text.
* As you read, record which elements were viewed and when.
* Store this in a `read_history` table linked to both user and article.
* This forms the foundation for future personalization (ranking, quizzes, memory recall).

---

## **Phase 5 — News Integration and Priority Ranking**

### **Goals**

Dynamically re-rank your saved articles based on current events.

### **Tasks**

* Integrate a **news API** (choose one to start):

  * Twitter/X, Hacker News, Reddit, or Google News.
* Use the day’s trending topics to **re-rank your saved articles** by relevance or importance.

  * Example: if global coverage focuses on AI regulation, surface your saved AI-policy articles higher.

---

## **Phase 6 — Memory-Informed Re-Ranking**

### **Goals**

Enhance the re-ranking algorithm with your reading history.

### **Tasks**

* Combine current event data (Phase 5) with:

  * What you’ve already read.
  * What you’ve partially read or ignored.
  * Your historical topic preferences.
* The system learns over time to highlight the most relevant unread material based on your interests and memory footprint.

---

## **Phase 7 — AI Quizzing**

### **Goals**

Turn the reading process into an active learning experience.

### **Tasks**

* Add a “Generate Quiz” button for any article.
* Automatically generate comprehension questions using AI.
* User answers within the app.
* AI evaluates and provides feedback:

  * Marks as correct or incorrect.
  * Offers an explanation or reference passage.
* Store quiz results to further refine your memory model.

---

## **Summary of Stack Considerations**

| Layer              | Options                                               |
| ------------------ | ----------------------------------------------------- |
| Backend            | Supabase and FastAPI                                  |
| Frontend           | React                                                 |
| AI Integration     | OpenAI API (GPT-4-mini / GPT-4-turbo)                 |
| Storage            | PostgreSQL (for articles + read history)              |
| Content Extraction | Mercury Parser, Newspaper3k, or GPT-4-mini            |
| News Source        | Google News API, Twitter/X API, or Hacker News RSS    |
| Hosting            | Vercel / Fly.io for frontend, Supabase backend        |

