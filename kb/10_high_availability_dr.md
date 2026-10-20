# High availability and disaster recovery on AWS

High availability means surviving the loss of a component or an Availability Zone. Disaster recovery means recovering from the loss of a whole Region.

## Availability targets
99.9 percent availability allows roughly 8.8 hours of downtime a year and is achievable with a multi-AZ design. 99.99 percent allows about 53 minutes a year and normally needs automated failover, health checks and tested recovery. Higher targets need multi-Region designs with Route 53 health checks and failover routing.

## DR strategies
Backup and restore is cheapest with recovery in hours. Pilot light keeps core data replicated and infrastructure ready to start. Warm standby runs a scaled-down copy and scales up on failover. Multi-site active-active has the best recovery time at the highest cost. Choose the strategy from the business recovery time objective (RTO) and recovery point objective (RPO), not from habit. Test failover regularly.
