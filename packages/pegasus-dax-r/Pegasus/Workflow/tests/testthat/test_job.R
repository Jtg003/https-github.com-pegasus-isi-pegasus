library(pegasus)
context('Test Job')

# setup
x1 <- Transformation('mDiff',namespace='montage',version='3.0')
e1 <- Executable(namespace='os',name='grep',version='2.3',arch=Pegasus.Arch$X86,os=Pegasus.OS$LINUX)
input <- File("i1.txt")
output <- File("o1.txt")
i1 <- Invoke(Pegasus.When$AT_END, '/usr/bin/mail -s "job done" rafsilva@isi.edu')
i2 <- Invoke(Pegasus.When$ON_ERROR, '/usr/bin/update_db -failure')

jx <- Job(x1, id='ID000001')
je <- Job(e1, id='ID000002')
j1 <- Job('job-1', id='ID000003')

jx <- AddArguments(jx, list("-i",input,"-o",output))
je <- AddArguments(je, list("-i",input,"-o",output))
j1 <- AddArguments(j1, list("-i",input,"-o",output))
jx <- AddProfile(jx, Profile(Pegasus.Namespace$ENV, key='PATH', value='/bin'))
je <- AddProfile(je, Profile(Pegasus.Namespace$ENV, key='PATH', value='/bin'))
j1 <- AddProfile(j1, Profile(Pegasus.Namespace$ENV, key='PATH', value='/bin'))
jx <- AddInvoke(jx, i1)
jx <- AddInvoke(jx, i2)
je <- Metadata(je, 'size', '1024')
je <- Metadata(je, 'createdby', 'Rafael Ferreira da Silva')

jx <- Uses(jx, input, Pegasus.Link$INPUT)
jx <- Uses(jx, output, Pegasus.Link$OUTPUT, transfer=TRUE, register=TRUE)
je <- Uses(je, input, Pegasus.Link$INPUT)
je <- Uses(je, output, Pegasus.Link$OUTPUT, transfer=TRUE, register=TRUE)
j1 <- Uses(j1, input, Pegasus.Link$INPUT)
j1 <- Uses(j1, output, Pegasus.Link$OUTPUT, transfer=TRUE, register=TRUE)

dax <- Workflow('workflow-dax')
dax <- AddJob(dax, jx)
dax <- AddJob(dax, je)
dax <- AddJob(dax, j1)

test_that('job creation', {
  expect_true(Equals(jx, jx))
  expect_true(Equals(je, je))
  expect_true(Equals(j1, j1))
  expect_false(Equals(jx, je))
  expect_false(Equals(jx, j1))
  expect_false(Equals(je, j1))
  expect_match(jx$name, 'mDiff')
  expect_match(je$name, 'grep')
  expect_match(j1$name, 'job-1')
})

test_that('adding uses', {
  expect_error(Uses(jx, input), 'Duplicate Use:')
  expect_error(Uses(je, output), 'Duplicate Use:')
  expect_error(Uses(j1, input), 'Duplicate Use:')
  expect_equal(length(jx$abstract.job$use.mixin$used), 2)
  expect_is(jx$abstract.job$use.mixin$used[[1]]$name, 'File')
  expect_is(jx$abstract.job$use.mixin$used[[2]]$name, 'File')
})

test_that('adding profiles', {
  expect_error(AddProfile(jx, Profile(Pegasus.Namespace$ENV, 'PATH', '/bin')), 'Duplicate profile: /bin')
  expect_error(AddProfile(je, Profile(Pegasus.Namespace$ENV, 'PATH', '/bin')), 'Duplicate profile: /bin')
  expect_equal(length(j1$abstract.job$profile.mixin$profiles), 1)
  expect_is(jx$abstract.job$profile.mixin$profiles[[1]], 'Profile')
  expect_match(je$abstract.job$profile.mixin$profiles[[1]]$namespace, Pegasus.Namespace$ENV)
  expect_match(j1$abstract.job$profile.mixin$profiles[[1]]$key, 'PATH')
  expect_match(jx$abstract.job$profile.mixin$profiles[[1]]$value, '/bin')
})

test_that('adding metadata', {
  expect_error(Metadata(je, 'size', '1024'), 'Duplicate metadata: size')
  expect_error(Metadata(je, 'createdby', 'Rafael Ferreira da Silva'), 'Duplicate metadata: Rafael Ferreira da Silva')
  expect_equal(length(je$abstract.job$metadata.mixin$metadata.l), 2)
  expect_is(je$abstract.job$metadata.mixin$metadata.l[[1]], 'Metadata')
  expect_match(je$abstract.job$metadata.mixin$metadata.l[[2]]$key, 'createdby')
  expect_match(je$abstract.job$metadata.mixin$metadata.l[[1]]$value, '1024')
})

test_that('adding invokes', {
  expect_error(AddInvoke(jx, i1), 'Duplicate Invoke')
  expect_error(AddInvoke(jx, i2), 'Duplicate Invoke')
  expect_equal(length(jx$abstract.job$invoke.mixin$invocations), 2)
  expect_is(jx$abstract.job$invoke.mixin$invocations[[1]], 'Invoke')
  expect_match(jx$abstract.job$invoke.mixin$invocations[[1]]$when, Pegasus.When$AT_END)
  expect_match(jx$abstract.job$invoke.mixin$invocations[[2]]$what, '/usr/bin/update_db -failure')
})

test_that('manipulating jobs', {
  expect_equal(length(dax$jobs), 3)
  expect_true(HasJob(dax, jx))
  expect_true(HasJob(dax, je))
  expect_true(HasJob(dax, j1))
  expect_error(AddJob(dax, jx), 'Duplicate job')
  expect_error(AddJob(dax, je), 'Duplicate job')
  expect_error(AddJob(dax, j1), 'Duplicate job')

  dax <- RemoveJob(dax, jx)
  expect_equal(length(dax$jobs), 2)
  expect_false(HasJob(dax, jx))
  expect_true(HasJob(dax, je))
  expect_true(HasJob(dax, j1))
  dax <- RemoveJob(dax, je)
  expect_equal(length(dax$jobs), 1)
  expect_false(HasJob(dax, je))
  expect_false(HasJob(dax, jx))
  expect_true(HasJob(dax, j1))

  dax <- AddJob(dax, jx)
  dax <- AddJob(dax, je)
  dax <- ClearJobs(dax)
  expect_equal(length(dax$jobs), 0)
  expect_false(HasJob(dax, jx))
  expect_false(HasJob(dax, je))
  expect_false(HasJob(dax, j1))
})

test_that('YAML generation', {
  expect_equal(length(capture.output(WriteYAML(dax, stdout()))), 53)
})
