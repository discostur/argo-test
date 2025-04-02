#!/usr/bin/env python3
"""
PowerDNS Authoritative API Load Test Script

This script performs load testing on the PowerDNS Authoritative API by creating
and deleting zones. It measures performance metrics for API operations.

API Reference: https://doc.powerdns.com/authoritative/http-api/
"""

import argparse
import json
import random
import statistics
import string
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Tuple, Union

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class PDNSLoadTest:
    """PowerDNS API Load Test class"""

    def __init__(
        self,
        api_url: str,
        api_key: str,
        zone_prefix: str,
        server_id: str = "localhost",
        timeout: int = 30,
        verify_ssl: bool = True,
        max_workers: int = 10,
    ):
        """
        Initialize the PowerDNS Load Test client.

        Args:
            api_url: Base URL for the PowerDNS API (e.g., http://localhost:8081)
            api_key: API key for authentication
            zone_prefix: Prefix for zone names to be created
            server_id: PowerDNS server ID (default: localhost)
            timeout: Request timeout in seconds
            verify_ssl: Whether to verify SSL certificates
            max_workers: Maximum number of concurrent workers for parallel operations
        """
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.zone_prefix = zone_prefix
        self.server_id = server_id
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        self.max_workers = max_workers

        # Setup session with retry logic
        self.session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST", "PUT", "DELETE"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        
        # Set default headers
        self.session.headers.update({
            "X-API-Key": self.api_key,
            "Accept": "application/json",
            "Content-Type": "application/json"
        })

    def _make_request(
        self, method: str, endpoint: str, data: Optional[Dict] = None
    ) -> Tuple[requests.Response, float]:
        """
        Make an API request and measure the response time.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            endpoint: API endpoint
            data: Request data (for POST/PUT)

        Returns:
            Tuple of (response, response_time)
        """
        url = f"{self.api_url}/api/v1/servers/{self.server_id}/{endpoint}"
        
        start_time = time.time()
        try:
            if method == "GET":
                response = self.session.get(
                    url, timeout=self.timeout, verify=self.verify_ssl
                )
            elif method == "POST":
                response = self.session.post(
                    url, json=data, timeout=self.timeout, verify=self.verify_ssl
                )
            elif method == "PUT":
                response = self.session.put(
                    url, json=data, timeout=self.timeout, verify=self.verify_ssl
                )
            elif method == "DELETE":
                response = self.session.delete(
                    url, timeout=self.timeout, verify=self.verify_ssl
                )
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
            
            response_time = time.time() - start_time
            return response, response_time
        
        except requests.RequestException as e:
            print(f"Request error: {e}")
            response_time = time.time() - start_time
            return None, response_time

    def list_zones(self) -> Tuple[List[Dict], float]:
        """
        List all zones from the PowerDNS server.

        Returns:
            Tuple of (zones_list, response_time)
        """
        response, response_time = self._make_request("GET", "zones")
        
        if response and response.status_code == 200:
            return response.json(), response_time
        else:
            status_code = response.status_code if response else "No response"
            print(f"Failed to list zones. Status code: {status_code}")
            return [], response_time

    def create_zone(self, zone_name: str) -> Tuple[bool, float]:
        """
        Create a new zone.

        Args:
            zone_name: Name of the zone to create

        Returns:
            Tuple of (success, response_time)
        """
        # Ensure zone name ends with a dot
        if not zone_name.endswith("."):
            zone_name = f"{zone_name}."
            
        zone_data = {
            "name": zone_name,
            "kind": "Native",
            "nameservers": ["ns1.example.com.", "ns2.example.com."],
            "soa_edit_api": "INCEPTION-INCREMENT",
            "soa_edit": "INCEPTION-INCREMENT"
        }
        
        response, response_time = self._make_request("POST", "zones", zone_data)
        
        if response and response.status_code in (201, 200):
            return True, response_time
        else:
            status_code = response.status_code if response else "No response"
            error_msg = response.text if response else "Unknown error"
            print(f"Failed to create zone {zone_name}. Status code: {status_code}, Error: {error_msg}")
            return False, response_time

    def delete_zone(self, zone_name: str) -> Tuple[bool, float]:
        """
        Delete a zone.

        Args:
            zone_name: Name of the zone to delete

        Returns:
            Tuple of (success, response_time)
        """
        # Ensure zone name ends with a dot
        if not zone_name.endswith("."):
            zone_name = f"{zone_name}."
            
        response, response_time = self._make_request("DELETE", f"zones/{zone_name}")
        
        if response and response.status_code == 204:
            return True, response_time
        else:
            status_code = response.status_code if response else "No response"
            error_msg = response.text if response else "Unknown error"
            print(f"Failed to delete zone {zone_name}. Status code: {status_code}, Error: {error_msg}")
            return False, response_time

    def get_zones_with_prefix(self) -> List[str]:
        """
        Get all zones that start with the configured prefix.

        Returns:
            List of zone names
        """
        zones, _ = self.list_zones()
        return [zone["name"] for zone in zones if zone["name"].startswith(self.zone_prefix)]

    def generate_random_suffix(self, length: int = 8) -> str:
        """
        Generate a random string to use as a zone name suffix.

        Args:
            length: Length of the random string

        Returns:
            Random string
        """
        return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

    def create_zones(self, count: int, parallel: bool = False) -> Dict:
        """
        Create multiple zones with the configured prefix.

        Args:
            count: Number of zones to create
            parallel: Whether to create zones in parallel

        Returns:
            Dictionary with metrics
        """
        print(f"Creating {count} zones with prefix '{self.zone_prefix}'...")
        
        start_time = time.time()
        successful_creations = 0
        failed_creations = 0
        response_times = []
        
        zone_names = [
            f"{self.zone_prefix}{self.generate_random_suffix()}.com"
            for _ in range(count)
        ]
        
        if parallel and self.max_workers > 1:
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                results = list(executor.map(self.create_zone, zone_names))
                
            for success, response_time in results:
                if success:
                    successful_creations += 1
                else:
                    failed_creations += 1
                response_times.append(response_time)
        else:
            for zone_name in zone_names:
                success, response_time = self.create_zone(zone_name)
                if success:
                    successful_creations += 1
                else:
                    failed_creations += 1
                response_times.append(response_time)
                
        total_time = time.time() - start_time
        
        metrics = {
            "operation": "create",
            "total_zones": count,
            "successful": successful_creations,
            "failed": failed_creations,
            "total_time_seconds": total_time,
            "average_time_per_zone": total_time / count if count > 0 else 0,
            "response_times": {
                "min": min(response_times) if response_times else 0,
                "max": max(response_times) if response_times else 0,
                "avg": statistics.mean(response_times) if response_times else 0,
                "median": statistics.median(response_times) if response_times else 0,
            }
        }
        
        return metrics

    def delete_zones_with_prefix(self, parallel: bool = False) -> Dict:
        """
        Delete all zones that start with the configured prefix.

        Args:
            parallel: Whether to delete zones in parallel

        Returns:
            Dictionary with metrics
        """
        zones_to_delete = self.get_zones_with_prefix()
        count = len(zones_to_delete)
        
        if count == 0:
            print(f"No zones found with prefix '{self.zone_prefix}'")
            return {
                "operation": "delete",
                "total_zones": 0,
                "successful": 0,
                "failed": 0,
                "total_time_seconds": 0,
            }
        
        print(f"Deleting {count} zones with prefix '{self.zone_prefix}'...")
        
        start_time = time.time()
        successful_deletions = 0
        failed_deletions = 0
        response_times = []
        
        if parallel and self.max_workers > 1:
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                results = list(executor.map(self.delete_zone, zones_to_delete))
                
            for success, response_time in results:
                if success:
                    successful_deletions += 1
                else:
                    failed_deletions += 1
                response_times.append(response_time)
        else:
            for zone_name in zones_to_delete:
                success, response_time = self.delete_zone(zone_name)
                if success:
                    successful_deletions += 1
                else:
                    failed_deletions += 1
                response_times.append(response_time)
                
        total_time = time.time() - start_time
        
        metrics = {
            "operation": "delete",
            "total_zones": count,
            "successful": successful_deletions,
            "failed": failed_deletions,
            "total_time_seconds": total_time,
            "average_time_per_zone": total_time / count if count > 0 else 0,
            "response_times": {
                "min": min(response_times) if response_times else 0,
                "max": max(response_times) if response_times else 0,
                "avg": statistics.mean(response_times) if response_times else 0,
                "median": statistics.median(response_times) if response_times else 0,
            }
        }
        
        return metrics

    def print_metrics(self, metrics: Dict) -> None:
        """
        Print performance metrics in a readable format.

        Args:
            metrics: Dictionary with metrics
        """
        operation = metrics["operation"].capitalize()
        print(f"\n{operation} Operation Metrics:")
        print(f"  Total zones: {metrics['total_zones']}")
        print(f"  Successful: {metrics['successful']}")
        print(f"  Failed: {metrics['failed']}")
        print(f"  Total time: {metrics['total_time_seconds']:.2f} seconds")
        
        if metrics['total_zones'] > 0:
            print(f"  Average time per zone: {metrics['average_time_per_zone']:.4f} seconds")
            
            if 'response_times' in metrics:
                print("  API Response Times (seconds):")
                print(f"    Min: {metrics['response_times']['min']:.4f}")
                print(f"    Max: {metrics['response_times']['max']:.4f}")
                print(f"    Avg: {metrics['response_times']['avg']:.4f}")
                print(f"    Median: {metrics['response_times']['median']:.4f}")
        
        success_rate = (metrics['successful'] / metrics['total_zones'] * 100) if metrics['total_zones'] > 0 else 0
        print(f"  Success rate: {success_rate:.2f}%")


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="PowerDNS Authoritative API Load Test Tool",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    parser.add_argument(
        "--url", 
        required=True,
        help="PowerDNS API URL (e.g., http://localhost:8081)"
    )
    parser.add_argument(
        "--key", 
        required=True,
        help="PowerDNS API key"
    )
    parser.add_argument(
        "--server-id", 
        default="localhost",
        help="PowerDNS server ID"
    )
    parser.add_argument(
        "--prefix", 
        default="loadtest-",
        help="Prefix for zone names"
    )
    parser.add_argument(
        "--count", 
        type=int, 
        default=10,
        help="Number of zones to create"
    )
    parser.add_argument(
        "--timeout", 
        type=int, 
        default=30,
        help="API request timeout in seconds"
    )
    parser.add_argument(
        "--no-verify-ssl", 
        action="store_true",
        help="Disable SSL certificate verification"
    )
    parser.add_argument(
        "--parallel", 
        action="store_true",
        help="Perform operations in parallel"
    )
    parser.add_argument(
        "--workers", 
        type=int, 
        default=10,
        help="Number of worker threads for parallel operations"
    )
    parser.add_argument(
        "--create-only", 
        action="store_true",
        help="Only create zones, don't delete"
    )
    parser.add_argument(
        "--delete-only", 
        action="store_true",
        help="Only delete zones with prefix, don't create"
    )
    parser.add_argument(
        "--list-only", 
        action="store_true",
        help="Only list zones with prefix, don't create or delete"
    )
    
    return parser.parse_args()


def main():
    """Main function."""
    args = parse_arguments()
    
    # Validate arguments
    if args.create_only and args.delete_only:
        print("Error: Cannot specify both --create-only and --delete-only")
        sys.exit(1)
    
    # Initialize the load test client
    load_test = PDNSLoadTest(
        api_url=args.url,
        api_key=args.key,
        zone_prefix=args.prefix,
        server_id=args.server_id,
        timeout=args.timeout,
        verify_ssl=not args.no_verify_ssl,
        max_workers=args.workers
    )
    
    # Print configuration
    print("\nPowerDNS Load Test Configuration:")
    print(f"  API URL: {args.url}")
    print(f"  Server ID: {args.server_id}")
    print(f"  Zone prefix: {args.prefix}")
    print(f"  Parallel execution: {'Yes' if args.parallel else 'No'}")
    if args.parallel:
        print(f"  Worker threads: {args.workers}")
    print()
    
    # List zones with prefix
    if args.list_only:
        zones = load_test.get_zones_with_prefix()
        print(f"Found {len(zones)} zones with prefix '{args.prefix}':")
        for zone in zones:
            print(f"  {zone}")
        return
    
    # Create zones
    if not args.delete_only:
        create_metrics = load_test.create_zones(args.count, args.parallel)
        load_test.print_metrics(create_metrics)
    
    # Delete zones
    if not args.create_only:
        delete_metrics = load_test.delete_zones_with_prefix(args.parallel)
        load_test.print_metrics(delete_metrics)


if __name__ == "__main__":
    main()
