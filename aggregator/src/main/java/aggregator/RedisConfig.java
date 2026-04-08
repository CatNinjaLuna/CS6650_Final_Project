package aggregator;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.data.redis.connection.RedisConnectionFactory;
import org.springframework.data.redis.listener.PatternTopic;
import org.springframework.data.redis.listener.RedisMessageListenerContainer;

/**
 * Configures Redis pub/sub subscription for the aggregator.
 *
 * Registers RedisSubscriber as a listener on the "roboparam:results" channel.
 * The connection factory is auto-configured by Spring Boot using the host/port
 * defined in application.properties (192.168.1.3:6379 — Windows machine running Docker).
 */
@Configuration
public class RedisConfig {

  /**
   * Creates the listener container that drives the Redis pub/sub loop.
   * Spring manages its lifecycle — starts on app startup, shuts down cleanly on exit.
   *
   * @param connectionFactory auto-configured from application.properties
   * @param subscriber        the bean that handles incoming messages
   */
  @Bean
  public RedisMessageListenerContainer redisContainer(
      RedisConnectionFactory connectionFactory,
      RedisSubscriber subscriber) {

    RedisMessageListenerContainer container = new RedisMessageListenerContainer();
    container.setConnectionFactory(connectionFactory);
    // Subscribe to all messages published to "roboparam:results"
    container.addMessageListener(subscriber, new PatternTopic("roboparam:results"));
    return container;
  }
}