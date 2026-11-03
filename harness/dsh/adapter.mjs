// Thin command adapter for the real DSH goal service and round driver.
// It submits one human /goal command; it never manufactures continuation turns.
import { randomUUID } from 'node:crypto'
import { readFile, writeFile } from 'node:fs/promises'
import { installModelSelection } from '@deepseek-ai/dsh-agent'
import { createUserMessage } from '@deepseek-ai/dsh-llm'
import { setApprovalPolicy } from '@deepseek-ai/dsh-user-approval'

export const name = 'benchmark-goal-adapter'
export const inject = ['agents', 'agentDefaultModel', 'sessions', 'commands', 'goals', 'permissionPresets', 'approval']

async function run(ctx) {
  await ctx.loader.await()
  const config = JSON.parse(await readFile('/home/agent/run/config.json', 'utf8'))
  const task = await readFile('/home/agent/task.md', 'utf8')
  if (task !== config.task) throw new Error('shared task does not match run config')
  const selection = ctx.agentDefaultModel.currentSelection()
  const { agent } = await ctx.agents.create({
    sessionId: `session-${randomUUID()}`,
    meta: { cwd: process.cwd() },
    agentOptions: { ...selection },
    setup: agentCtx => { installModelSelection(agentCtx, { current: selection, assembled: undefined }) },
  })
  await agent.whenIdle()
  ctx.permissionPresets.set(agent.session, 'workspace-write')
  setApprovalPolicy(agent.session, 'never')
  agent.followup(createUserMessage({ content: [{ type: 'text', text: 'Session initialisation check. Reply with OK and nothing else.' }], source: { kind: 'user' } }))
  await agent.whenIdle()
  await ctx.sessions.flush(agent.session)
  const start = Date.now()
  const deadline = start + config.max_seconds * 1000
  const result = await ctx.commands.execute(agent, `/goal ${task}`, [], new AbortController().signal)
  if (!result || result.result?.kind !== 'success') throw new Error(`goal command failed: ${JSON.stringify(result)}`)
  let goal
  while (Date.now() < deadline) {
    goal = ctx.goals.get(agent)
    if (goal && goal.phase !== 'active') break
    await new Promise(resolve => setTimeout(resolve, 500))
  }
  goal = ctx.goals.get(agent)
  if (!goal) throw new Error('goal disappeared')
  if (goal.phase === 'active') await agent.abort?.()
  else await agent.whenIdle()
  await ctx.sessions.flush(agent.session)
  const state = {
    name: config.name, trial: config.trial, session_id: agent.session.id,
    exit_reason: goal.phase === 'active' ? 'wall_clock_limit' : `goal_${goal.phase}`,
    native_goal: goal, objective_matches_normalized_task: goal.objective === (task.endsWith('\n') ? task.slice(0, -1) : task),
    auditor: 'not_applicable', elapsed_seconds: (Date.now() - start) / 1000,
  }
  await writeFile('/home/agent/logs/final-state.json', JSON.stringify(state, null, 2))
  ctx.appExit(goal.phase === 'complete' ? 0 : 1)
}

export function apply(ctx) {
  void run(ctx).catch(error => {
    console.error('benchmark goal adapter:', error?.stack ?? error)
    ctx.appExit(1)
  })
}
