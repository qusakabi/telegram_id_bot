import re
import logging
from typing import List, Set, Tuple
from collections import defaultdict

# Logging setup
logger = logging.getLogger(__name__)

# Regular expressions
email_regex = re.compile(r'^[\w\.-]+@([\w\.-]+\.\w{2,})$')
domain_from_url = re.compile(r"https?://(?:www\.)?([^/\s]+)")
url_regex = re.compile(r'https?://[^\s]+')
phone_regex = re.compile(r'[\+]?[1-9][\d]{0,15}')


class TextProcessor:
    """Class for processing text files"""

    @staticmethod
    def _extract_main_domain(domain: str) -> str:
        """
        Extracts the main domain from a subdomain.
        Example: contacts.google.com -> google.com
        """
        parts = domain.split('.')
        if len(parts) >= 2:
            # Take the last two parts for the main domain
            return '.'.join(parts[-2:])
        return domain

    @staticmethod
    async def process_smart_clean(file_path: str, new_path: str) -> None:
        """
        Smart cleaning and domain grouping:
        - Groups by main domain
        - Counts duplicates
        - Output format: domain.com (count)
        """
        try:
            logger.info(f"Starting smart processing of file: {file_path}")

            # Dictionary to count domains
            domain_counts = defaultdict(int)
            all_domains = set()

            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    # Take only the first column (before first space or tab)
                    domain = line.split()[0].lstrip('.')
                    if domain:
                        all_domains.add(domain)
                        # Extract main domain
                        main_domain = TextProcessor._extract_main_domain(domain)
                        domain_counts[main_domain] += 1

            # Sort by count (descending), then alphabetically
            sorted_domains = sorted(domain_counts.items(),
                                    key=lambda x: (-x[1], x[0]))

            with open(new_path, 'w', encoding='utf-8') as f:
                for main_domain, count in sorted_domains:
                    f.write(f"{main_domain} ({count})\n")

                # Add statistics
                f.write(f"\n=== STATISTICS ===\n")
                f.write(f"Total unique lines: {len(all_domains)}\n")
                f.write(f"Unique main domains: {len(domain_counts)}\n")
                f.write(f"Most frequent domain: {sorted_domains[0][0]} ({sorted_domains[0][1]} times)\n")

            logger.info(f"Smart processing completed. Result saved to: {new_path}")

        except Exception as e:
            logger.error(f"Error during smart processing of file {file_path}: {e}")
            raise

    @staticmethod
    async def process_clean(file_path: str, new_path: str) -> None:
        """
        Basic text cleaning and formatting:
        - Remove duplicates
        - Strip extra characters
        - Sort alphabetically
        """
        try:
            logger.info(f"Starting basic processing of file: {file_path}")

            domains = set()
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    # Take only the first column (before first space or tab)
                    domain = line.split()[0].lstrip('.')
                    domains.add(domain)

            with open(new_path, 'w', encoding='utf-8') as f:
                for domain in sorted(domains):
                    f.write(domain + '\n')

            logger.info(f"Processing completed. Result saved to: {new_path}")

        except Exception as e:
            logger.error(f"Error during processing of file {file_path}: {e}")
            raise

    @staticmethod
    async def process_dedup(file_path: str, new_path: str) -> None:
        """
        Deduplication of user:password files:
        - Group by user
        - Remove duplicate passwords
        - Formatted output
        """
        try:
            logger.info(f"Starting deduplication of file: {file_path}")

            user_pass_pairs = []
            user_domains = defaultdict(set)
            user_info = {}

            current_user = None
            current_url = None

            with open(file_path, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    try:
                        line = line.strip()
                        if not line:
                            continue

                        if line.startswith("URL:"):
                            url = line[4:].strip()
                            match = domain_from_url.match(url)
                            current_url = match.group(1) if match else None

                        elif line.startswith("USER:"):
                            user = line[5:].strip()
                            if email_regex.match(user):
                                current_user = user
                                if current_url:
                                    user_domains[current_user].add(current_url)
                                user_info[current_user] = {
                                    'domains': user_domains[current_user],
                                    'passwords': set()
                                }
                            else:
                                current_user = None

                        elif line.startswith("PASS:") and current_user:
                            password = line[5:].strip()
                            if password:
                                user_pass_pairs.append((current_user, password))
                                user_info[current_user]['passwords'].add(password)
                            current_user = None

                    except Exception as e:
                        logger.warning(f"Error processing line {line_num}: {e}")
                        continue

            # Remove duplicate pairs
            unique_pairs = list(set(user_pass_pairs))

            # Group by users
            users = sorted(set([user for user, _ in unique_pairs]))
            all_passwords = set()

            for user, password in unique_pairs:
                all_passwords.add(password)

            # Write result
            with open(new_path, 'w', encoding='utf-8') as f:
                # Header
                f.write("=== USERS ===\n\n")

                # Users with their domains
                for i, user in enumerate(users, 1):
                    domains = sorted(user_info[user]['domains'])
                    domain_str = ", ".join(domains) if domains else "no data"
                    f.write(f"{i}. {user} (domains: {domain_str})\n")

                f.write(f"\n=== PASSWORDS ({len(all_passwords)} unique) ===\n\n")

                # Passwords
                for i, password in enumerate(sorted(all_passwords), 1):
                    f.write(f"{i}. {password}\n")

                # Statistics
                f.write(f"\n=== STATISTICS ===\n")
                f.write(f"Total users: {len(users)}\n")
                f.write(f"Total passwords: {len(all_passwords)}\n")
                f.write(f"Total records: {len(unique_pairs)}\n")

            logger.info(f"Deduplication completed. Result saved to: {new_path}")

        except Exception as e:
            logger.error(f"Error during deduplication of file {file_path}: {e}")
            raise

    @staticmethod
    def _clean_line(line: str) -> str:
        """Clean a single line"""
        # Remove extra whitespace
        line = ' '.join(line.split())

        # Strip special characters from start/end
        line = line.strip('.,;:!?-_')

        # Validate domain/URL
        if line.startswith('http'):
            match = domain_from_url.match(line)
            if match:
                return match.group(1)
        elif '.' in line and not line.startswith('.'):
            # Plain domain
            return line.lstrip('.')

        return line

    @staticmethod
    async def process_advanced_clean(file_path: str, new_path: str) -> None:
        """
        Advanced text cleaning:
        - Remove URLs
        - Remove email addresses
        - Remove phone numbers
        - Strip HTML tags
        """
        try:
            logger.info(f"Starting advanced cleaning of file: {file_path}")

            cleaned_lines = []

            with open(file_path, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    try:
                        line = line.strip()
                        if not line:
                            continue

                        # Remove URLs
                        line = url_regex.sub('', line)

                        # Remove email addresses
                        line = email_regex.sub('', line)

                        # Remove phone numbers
                        line = phone_regex.sub('', line)

                        # Remove HTML tags
                        line = re.sub(r'<[^>]+>', '', line)

                        # Strip extra characters
                        line = re.sub(r'[^\w\s\.-]', '', line)
                        line = ' '.join(line.split())

                        if line and len(line) > 2:
                            cleaned_lines.append(line)

                    except Exception as e:
                        logger.warning(f"Error processing line {line_num}: {e}")
                        continue

            # Remove duplicates and sort
            unique_lines = sorted(set(cleaned_lines))

            with open(new_path, 'w', encoding='utf-8') as f:
                for line in unique_lines:
                    f.write(line + '\n')

            logger.info(f"Advanced cleaning completed. Result saved to: {new_path}")

        except Exception as e:
            logger.error(f"Error during advanced cleaning of file {file_path}: {e}")
            raise


# Backward compatibility functions
async def process_clean(file_path: str, new_path: str) -> None:
    """Backward compatibility with original function"""
    await TextProcessor.process_clean(file_path, new_path)


async def process_dedup(file_path: str, new_path: str) -> None:
    """Backward compatibility with original function"""
    await TextProcessor.process_dedup(file_path, new_path)


# Additional functions
async def process_advanced_clean(file_path: str, new_path: str) -> None:
    """Advanced text cleaning"""
    await TextProcessor.process_advanced_clean(file_path, new_path)


async def process_smart_clean(file_path: str, new_path: str) -> None:
    """Smart cleaning with domain grouping"""
    await TextProcessor.process_smart_clean(file_path, new_path)