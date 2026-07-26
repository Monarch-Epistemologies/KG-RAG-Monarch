# My laptop wasn't crashing. It was overheating in slow motion.

*A MacBook Air is cool, until it isn't.*

I was embedding 300,000 short biomedical text documents (snippets) into
vectors — the kind of job that's supposed to be boring. Run a
sentence-transformer model over a pile of text, write the output to a
database, go do something else for twenty minutes. On paper the arithmetic was trivial: cool, the model on my Mac's GPU
was doing about 400 documents a second, which puts the whole corpus under
thirteen minutes.

It took four hours to get halfway, and I killed it.

I built this pipeline with Claude Code. Most of the code was written by a
model, at a speed I couldn't match by hand, and so were several of the
diagnoses below. The whole thing — corpus extraction, embedding, a vector
store, four retrieval methods and their evaluation — took about a week of
near-full-time work.

## The first bottleneck wasn't the one I expected

My first guess was that the model itself was slow — a modern transformer
doing hundreds of thousands of forward passes is the kind of thing that
*sounds* expensive. But the machine didn't look like it was working hard. A
few percent CPU, the GPU warm but not scorching hot, the output file crawling
forward one row at a time. If the model were the bottleneck, the GPU would have been pinned at
100%. It wasn't, which meant something downstream of it was starving it.

The something turned out to be the database write. I was inserting each
768-number vector into DuckDB one row at a time, and that path was roughly
thirty times slower than the encoding feeding it — so the GPU spent almost all
its time waiting on the previous insert to finish. Claude found that, quickly,
once I described the symptom — idle CPU, cold GPU, crawling output. The same
speed that had produced a row-by-row insert nobody stopped to think about also
produced the diagnosis of it, about a minute later. The fix was mechanical:
encode a batch, hand the whole batch to DuckDB as one columnar block instead
of one row at a time, let it ingest in a single call. Same vectors, same
table. A smoke test on three thousand documents then ran at the GPU's full
rate — about 430 documents a second, right where the math said it should be.

I thought that was the whole story. It wasn't.

## The "hang" that wasn't a hang

With the insert fixed, the real run took off — and then, around the
hundred-thousand-document mark, it appeared to stop. Not crashed, exactly.
The process just sat there, the progress log frozen for minutes at a time, in
that specific uninterruptible-looking way that usually means something in the
driver stack has wedged.

Claude's read was that GPU-accelerated embedding on this machine was simply
unstable — that Apple's Metal backend had some flaky failure mode under
sustained load, and the right response was to stop trusting it for long runs.
It fit the symptom, and I took it.

That was about as wrong as a diagnosis can be, and what made it stick was that
it was *plausible* — plausible enough to discuss, to plan around, to start
writing retry logic for.

Both problems got debugged exactly the same way, and only one of them cracked.
The insert symptom travelled: idle CPU, an unstressed GPU, slow output is a pattern,
and a pattern survives being described to someone who isn't there. A GPU
parked in a cooling cycle isn't a pattern. It leaves no trace in anything you
can paste into a chat window — only a reading on the machine, which nobody had
gone and taken.

## What was actually happening: the chip was cooking itself

The machine is a fanless MacBook Air. No moving parts, no airflow — it sheds
heat entirely through the aluminum chassis, which is a fine design for
bursty work and a bad one for anything sustained. I only found this out
because I stopped guessing and watched the machine with `powermetrics`, which
reports real thermal state, instead of `pmset`, the tool I'd tried first
because it doesn't need `sudo`. `pmset` reported nothing unusual the entire
time. `powermetrics` showed the SoC sitting under *Heavy* thermal pressure for
most of the run.

Under that pressure, the chip doesn't just slow its clock. Claude explained
that it periodically parks the GPU entirely, forcing it idle in short cooling
cycles. A batch that
took fifty seconds when the machine was cool took four to eight minutes once
it was hot. The log wasn't frozen. It was working the whole time, just at a
small fraction of its real speed, long enough between updates to look dead.

The counterintuitive part: clock speed alone didn't tell the story. A batch
could flash up to 1100 MHz for an instant and still take minutes, because
what actually governs throughput is the *duty cycle* — the fraction of time
the GPU spends executing versus parked to cool off — not the peak number it
briefly touches. Thermal pressure is a slow, laggy signal covering the whole
chip; the clock speed is fast and bursty. Neither one, on its own, tells you
the number that matters, which is how much of the last minute the GPU
actually spent computing.

## The fix was a fan, not a rewrite

Once the diagnosis was thermal rather than software, the fix was physical —
which is the one category of fix no amount of assistance could have written
for me. The laptop had a protective case on its underside, insulating the
exact aluminum surface that is the heatsink on a fanless machine. I took the
case off and pointed a small desk fan at the bare metal over the chip.

The GPU boosted past 900 MHz for the first time in the whole run, and the
deep stalls stopped. What the fan bought was not speed but *steadiness*: the
job settled at roughly a hundred documents a second and held there, instead
of sagging into multi-minute pauses. The full corpus finished, throttled and
hand-cooled, in about fifty minutes — against the twelve it would have taken
had the chip stayed cool throughout.

That gap is the real number, and it's worth being precise about which
direction it points. Cool, the machine holds around 400 documents a second.
Under the thermal pressure that builds in after roughly the first sixty
thousand documents, the sustained average — not the instantaneous dip, the
number that actually determines how long the job takes — falls to around 110.
Hand-cooling kept it *at* that 110 rather than lifting it back toward 400. For
a 300,000-document corpus that's the difference between about twelve minutes
and fifty. For a four-million-document one, it's the difference between an
afternoon and most of a day.

I tried other cooling arrangements after that — case off with no fan, the
laptop propped vertical in a stand for better convection, the fan pointed at
different spots — and they moved the throttled rate around within a band of
roughly 60 to 150 documents a second. None of them got back to the cool
baseline of 400. External cooling can nudge a fanless chassis. It can't turn
it into a chassis with a fan.

## The hardware ladder, and the rung I'd skipped

I'd started this project with a rule about hardware: run everything on the
laptop until some measured cost proves it can't, and only then rent a real
GPU in the cloud. Two rungs — the machine I own, and the machine I'd pay by
the hour for — with a tripwire between them. Watching a fanless laptop cook
itself for four hours looks a lot like that tripwire going off.

It wasn't, and working out why is what turned two rungs into three. Renting a
cloud GPU is not a bigger version of the machine I have; it's a different
architecture, a different acceleration stack, and — because containers on
Apple Silicon can't reach the GPU at all — a full port rather than a move.
That's a real cost, and it's only worth paying for a problem that's genuinely
architectural. Mine wasn't. Mine was that the chassis couldn't shed heat.

Which leaves an obvious middle rung I'd never considered, because I'd framed
the choice as "my laptop or the cloud." A high-spec Mac Mini is the same chip
family, the same Metal acceleration, the same code, unchanged — but with a
fan, so it holds full clock under sustained load instead of throttling after
a minute. It can also be configured with far more memory than a laptop's
sixteen gigabytes, which happens to lift the *other* ceiling this project
keeps drifting toward: the search index I'll eventually want to hold in RAM.
One actively-cooled desktop removes both walls at once, and it does it
without containers, without a port, without a cloud bill.

So the honest ladder has three rungs:

**A fanless MacBook Air** — fine for building, measuring, and one-time runs
that can be hand-cooled or left to crawl overnight. Thermally bound the
moment a job runs long enough to heat-soak the chassis, which in my case was
about sixty thousand documents in.

**A high-spec Mac Mini** — same stack, no port, no containers, no thermal
wall, and more memory. The correct answer to the limits I actually measured,
and the rung my original two-rung framing skipped entirely.

**A cloud GPU** — justified only by a need a single cooled desktop still
can't meet: raw parallel throughput across many machines, not just the
ability to stay cool. A different kind of problem from the one I had.

The tripwire, it turns out, was never "leave Apple Silicon." It was "leave
the *fanless* machine" — and those are two very different amounts of money.

So before assuming a workload needs bigger, more expensive infrastructure,
find out whether what's limiting it is heat. Stripping the case off and
pointing a fan at bare aluminum didn't make my laptop fast — it got the job
running steadily at around a hundred documents a second instead of stalling,
which was enough to finish. Getting back to the full four hundred was never
something cooling by hand could buy. That takes a machine built to stay cool.

A week of near-full-time work produced an embedding pipeline over a
multi-million-edge biomedical graph, four retrieval methods, and an evaluation
harness. It would not have, at that pace, without Claude Code — the code was
fast and so were most of the diagnoses, and the insert bottleneck was Claude's
find, not mine.

What didn't compress was the part that needed someone in the room. Throttling
leaves no symptom you can paste anywhere, only a reading on a machine that
somebody has to go and take. The plastic case was an object on a desk. Neither
is a hard problem. They just sit on the far side of a line the model can't
cross, and they cost me four hours because everything on the near side had been
moving fast enough that I'd stopped expecting to walk over there.
