use clap::{Parser, Subcommand};

mod config;
mod init;
mod run;
mod serve;
mod share;
mod start;

#[derive(Parser)]
#[command(
    name = "workers-spec",
    about = "Share Claude Code sessions as replayable specs",
    before_help = concat!(
        "\n\n",
        " ███████╗██████╗ ███████╗ ██████╗███████╗\n",
        " ██╔════╝██╔══██╗██╔════╝██╔════╝██╔════╝\n",
        " ███████╗██████╔╝█████╗  ██║     ███████╗\n",
        " ╚════██║██╔═══╝ ██╔══╝  ██║     ╚════██║\n",
        " ███████║██║     ███████╗╚██████╗███████║\n",
        " ╚══════╝╚═╝     ╚══════╝ ╚═════╝╚══════╝\n",
        "                          by workers.io\n",
    )
)]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand)]
enum Commands {
    /// View or update server configuration
    Config {
        /// Set the server URL (e.g. http://your-server:3005)
        #[arg(long)]
        server_url: Option<String>,
        /// Reset to default local server (http://localhost:3005)
        #[arg(long)]
        reset: bool,
    },
    /// Generate a spec from a Claude Code session and upload it
    Share {
        /// The Claude Code session ID
        session_id: String,
        /// Workspace path for session file lookup
        #[arg(long, short)]
        workspace: Option<String>,
    },
    /// Fetch and display a shared spec
    Run {
        /// Spec URL or ID
        url_or_id: String,
        /// Output full spec content instead of preview
        #[arg(long)]
        full: bool,
    },
    /// Start the spec server as a background daemon
    Start {
        /// Port to listen on
        #[arg(long, default_value = "3005")]
        port: u16,
    },
    /// Stop the running spec server
    Stop,
    /// Check if the spec server is running
    Status,
    /// Run the server in the foreground (used internally by start)
    #[command(hide = true)]
    Serve {
        /// Port to listen on
        #[arg(long, default_value = "3005")]
        port: u16,
        /// Path to SQLite database
        #[arg(long)]
        database_path: Option<String>,
    },
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let cli = Cli::parse();

    let log_level = match &cli.command {
        Commands::Serve { .. } => tracing::Level::INFO,
        _ => tracing::Level::WARN,
    };

    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::from_default_env()
                .add_directive(log_level.into()),
        )
        .init();

    match cli.command {
        Commands::Config { server_url, reset } => {
            init::run(server_url.as_deref(), reset)?;
        }
        Commands::Share {
            session_id,
            workspace,
        } => {
            share::run(&session_id, workspace.as_deref()).await?;
        }
        Commands::Run { url_or_id, full } => {
            run::run(&url_or_id, full).await?;
        }
        Commands::Start { port } => {
            start::start(port)?;
        }
        Commands::Stop => {
            start::stop()?;
        }
        Commands::Status => {
            start::status().await?;
        }
        Commands::Serve { port, database_path } => {
            let db_path = match database_path {
                Some(p) => p,
                None => start::database_path()?,
            };
            serve::run(port, &db_path).await?;
        }
    }

    Ok(())
}
