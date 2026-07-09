package main

import (
	"flag"
	"fmt"
	"os"
	"os/signal"
	"syscall"

	"github.com/twmb/franz-go/pkg/kfake"
)

func main() {
	port := flag.Int("port", 9092, "broker port")
	partitions := flag.Int("partitions", 1, "default topic partitions")
	dataDir := flag.String("data-dir", "", "persistence directory for broker state")
	syncWrites := flag.Bool("sync", false, "fsync every write for immediate restart durability")
	flag.Parse()

	opts := []kfake.Opt{
		kfake.NumBrokers(1),
		kfake.Ports(*port),
		kfake.DefaultNumPartitions(*partitions),
		kfake.AllowAutoTopicCreation(),
		kfake.WithLogger(kfake.BasicLogger(os.Stderr, kfake.LogLevelWarn)),
	}
	if *dataDir != "" {
		opts = append(opts, kfake.DataDir(*dataDir))
	}
	if *syncWrites {
		opts = append(opts, kfake.SyncWrites())
	}

	cluster, err := kfake.NewCluster(opts...)
	if err != nil {
		fmt.Fprintf(os.Stderr, "wio-kafka-broker start failed: %v\n", err)
		os.Exit(1)
	}
	defer cluster.Close()

	fmt.Printf("WIO-KAFKA-BROKER ready addrs=%v data_dir=%q sync=%v\n", cluster.ListenAddrs(), *dataDir, *syncWrites)

	sig := make(chan os.Signal, 1)
	signal.Notify(sig, os.Interrupt, syscall.SIGTERM)
	<-sig
	fmt.Println("WIO-KAFKA-BROKER stopping")
}
