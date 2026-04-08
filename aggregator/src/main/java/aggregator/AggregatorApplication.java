package aggregator;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * Entry point for the SnapGrid WebSocket aggregator.
 *
 * Responsibilities:
 *   - Subscribe to Redis channel "roboparam:results"
 *   - Fan out incoming Isaac Sim results to all connected frontend WebSocket clients
 *
 * Runs on port 8082. Frontend connects via ws://localhost:8082/ws/results.
 */
@SpringBootApplication
public class AggregatorApplication {
  public static void main(String[] args) {
    SpringApplication.run(AggregatorApplication.class, args);
  }
}