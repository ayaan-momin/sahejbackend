from flask import Flask, request, jsonify
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
from ratelimit import limits, sleep_and_retry
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
from flask_cors import CORS

app = Flask(__name__)
CORS(app, resources={r"/jobs": {"origins": "*"}})

retry_strategy = Retry(
    total=3,
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["HEAD", "GET", "OPTIONS"],
    backoff_factor=1
)
adapter = HTTPAdapter(max_retries=retry_strategy)

session = requests.Session()
session.mount("https://", adapter)
session.mount("http://", adapter)

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

@sleep_and_retry
@limits(calls=10, period=60) 
def make_request(url):
    try:
        response = session.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return response
    except requests.RequestException as e:
        print(f"Request failed: {str(e)}")
        return None

def parse_job(job):
    try:
        title = job.find('h3', class_='base-search-card__title').text.strip()
        company = job.find('h4', class_='base-search-card__subtitle').text.strip()
        location = job.find('span', class_='job-search-card__location').text.strip()
        salary = job.find('span', class_='job-search-card__salary-info')
        salary = salary.text.strip() if salary else 'Not provided'
        link = job.find('a', class_='base-card__full-link')['href']
        
        return {
            'title': title,
            'company': company,
            'location': location,
            'salary': salary,
            'link': link
        }
    except AttributeError as e:
        print(f"Error parsing job: {str(e)}")
        return None

def scrape_linkedin(title, location, start=0, num_jobs=10):
    url = f"https://www.linkedin.com/jobs/search?keywords={title}&location={location}&start={start}"
    print(f"Scraping LinkedIn URL: {url}")
    response = make_request(url)
    if not response:
        return []
    
    print(f"LinkedIn status code: {response.status_code}")
    soup = BeautifulSoup(response.content, 'html.parser')
    
    job_cards = soup.find_all('div', class_='base-card')
    print(f"Number of job cards found on LinkedIn: {len(job_cards)}")
    
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_job = {executor.submit(parse_job, job): job for job in job_cards[:num_jobs]}
        jobs = []
        for future in as_completed(future_to_job):
            result = future.result()
            if result:
                jobs.append(result)
    
    return jobs

@app.route('/jobs', methods=['GET'])
def jobs():
    title = request.args.get('title')
    location = request.args.get('location')
    num_jobs = int(request.args.get('num_jobs', 10))
    
    if not title or not location:
        return jsonify({"error": "Please provide both title and location parameters"}), 400
    
    linkedin_jobs = scrape_linkedin(title, location, num_jobs=num_jobs)
    
    if not linkedin_jobs:
        return jsonify({"message": "No jobs found"}), 404
    
    return jsonify(linkedin_jobs)

if __name__ == "__main__":
    app.run()